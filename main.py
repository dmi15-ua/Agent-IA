import logging
import os
import secrets

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Optional

import config
from database import db
from formularios import formularios, _permitido, _limpiar_mapa
from gemini_service import gemini_ai
from utils import normalizar_telefono
from whatsapp_service import whatsapp


def _permitido_por_ip(request: Request) -> bool:
    """Limita los envíos del formulario por IP. Delega en formularios.py."""
    return _permitido(request.client.host if request.client else "desconocido")


def _limpiar_mapa_ips() -> None:
    _limpiar_mapa()

# Configurar logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Agente IA de Recuperación de Llamadas para Clínicas",
    description="Backend que detecta llamadas perdidas y responde a pacientes por WhatsApp con Google Gemini y Supabase.",
    version="1.0.0"
)

# Servir la Landing Page en la raíz
landing_dir = os.path.join(os.path.dirname(__file__), "landing")
index_html = os.path.join(landing_dir, "index.html")


@app.get("/")
def home():
    """Raíz: sirve la landing de demostración si existe."""
    if os.path.exists(index_html):
        return FileResponse(index_html)
    return {
        "status": "online",
        "service": "Agente IA para Clínicas (Missed-Call to WhatsApp)",
        "docs": "/docs"
    }


@app.get("/api/health")
def health():
    """Sonda de estado para deploys: confirma si las dependencias están vivas."""
    return {
        "status": "online",
        "service": "Agente IA para Clínicas",
        "supabase": "configurado" if db.modo_demo is False else "modo demo",
        "gemini": "configurado" if config.GEMINI_API_KEY else "sin key",
        "whatsapp": "configurado" if config.WHATSAPP_API_URL else "modo simulación",
        "modelos_gemini": config.GEMINI_MODELS,
    }


class LlamadaPerdidaInput(BaseModel):
    clinica_id: str = Field(..., example="a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11")
    telefono: str = Field(..., example="+34600112233")
    nombre: Optional[str] = Field(None, example="Carlos García")

class MensajeEntranteInput(BaseModel):
    clinica_id: Optional[str] = Field(
        None,
        description="Si se omite, se usa la clínica de la demo.",
    )
    telefono: str = Field(..., example="+34600112233")
    mensaje: str = Field(..., example="Hola, quería saber el precio de una limpieza dental")


class LeadInput(BaseModel):
    clinica_nombre: str = Field(..., min_length=2, max_length=160,
                                example="Clínica Dental Central")
    telefono: str = Field(..., min_length=6, max_length=40,
                          example="+34600000000")
    contacto_nombre: Optional[str] = Field(None, max_length=160,
                                           example="Dra. Carmen")
    especialidad: Optional[str] = Field(None, max_length=80,
                                        example="Clínica Dental")
    # Honeypot. Los robots rellenan todos los campos; una persona no ve este
    # input porque está oculto. Si viene relleno, es un bot.
    web: Optional[str] = Field(None, max_length=100)

class AltaClinicaInput(BaseModel):
    clinica_nombre: str = Field(..., min_length=2, max_length=160)
    telefono: str = Field(..., min_length=6, max_length=40)
    contacto_nombre: Optional[str] = Field(None, max_length=160)
    email: Optional[str] = Field(None, max_length=160)
    especialidad: Optional[str] = Field(None, max_length=80)
    horario: Optional[str] = Field(None, max_length=300)
    direccion: Optional[str] = Field(None, max_length=300)
    whatsapp_number: Optional[str] = Field(None, max_length=40)
    servicios: str = Field(...,
                           description="Servicios con precios. Ej: 'Limpieza 45 EUR, "
                                       "empaste desde 50 EUR'",
                           min_length=10, max_length=3000)
    instrucciones: Optional[str] = Field(
        None, max_length=2000,
        description="Cómo debe ser el asistente: tono, si agenda citas, etc.")
    prohibiciones: Optional[str] = Field(
        None, max_length=2000,
        description="Lo que la IA NO debe decir: descuentos, financiación, seguros.")
    web: Optional[str] = Field(None, max_length=100)


CLINICA_DEMO_ID = "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"

# Sufijos de JID de WhatsApp. Solo el primero es un teléfono real al que se
# puede responder: los grupos se responden en otro sitio y el @lid es un
# identificador interno de dispositivo, no un número.
JID_PERSONAL = "@s.whatsapp.net"


def extraer_de_evolution(data: dict) -> dict:
    """
    Saca telefono / texto / nombre de un evento MESSAGES_UPSERT de Evolution API.

    Devuelve un dict con:
      telefono  - número sin sufijo, o None si el mensaje no se puede atender
      texto     - contenido del mensaje, o None si no hay texto
      nombre    - nombre que el paciente tiene guardado en WhatsApp, si lo envía
      descartar - True si hay que ignorar el evento
      motivo    - por qué se descarta, para dejarlo escrito en el log
    """
    key = data.get("key") or {}

    # Los mensajes que envía el propio bot también llegan al webhook. Si se
    # respondieran, el agente se contestaría a sí mismo en bucle.
    if key.get("fromMe", False):
        return {"descartar": True, "motivo": "mensaje enviado por el propio bot"}

    remote_jid = key.get("remoteJid") or ""
    if not remote_jid.endswith(JID_PERSONAL):
        # @g.us es un grupo, @lid es el ID de dispositivo que WhatsApp usa en
        # las conversaciones nuevas. En los dos casos no se puede responder.
        return {"descartar": True, "motivo": f"JID no respondible ({remote_jid or 'vacío'})"}

    mensaje = data.get("message") or {}

    # Un paciente puede escribir de diez maneras distintas. Si solo miramos
    # "conversation" nos quedamos mudos cuando manda una foto o, peor, una nota
    # de voz, que es de lo más habitual en una clínica.
    texto = (
        mensaje.get("conversation")
        or (mensaje.get("extendedTextMessage") or {}).get("text")
        or (mensaje.get("imageMessage") or {}).get("caption")
        or (mensaje.get("videoMessage") or {}).get("caption")
        or (mensaje.get("documentMessage") or {}).get("caption")
        or (mensaje.get("contactMessage") or {}).get("displayName")
        or (mensaje.get("buttonsResponseMessage") or {}).get("selectedButtonId")
        or ((mensaje.get("listResponseMessage") or {}).get("singleSelectReply") or {}).get("selectedRowId")
    )

    return {
        "telefono": remote_jid.split("@")[0],
        "texto": texto,
        "nombre": data.get("pushName") or None,
        "descartar": False,
        "motivo": "",
    }


def verificar_secreto(request: Request) -> None:
    """Protege los endpoints que consumen la IA.

    Sin WEBHOOK_SECRET configurado el endpoint queda cerrado: si no, cualquiera
    que conozca la URL podría gastar la cuota de Gemini a tu costa.
    """
    if not config.WEBHOOK_SECRET:
        raise HTTPException(
            status_code=503,
            detail="Endpoint deshabilitado: define WEBHOOK_SECRET en el .env para activarlo."
        )
    recibido = request.headers.get("X-Webhook-Secret", "")
    if not secrets.compare_digest(recibido, config.WEBHOOK_SECRET):
        logger.warning("Petición al webhook rechazada por secreto inválido")
        raise HTTPException(status_code=401, detail="Secreto de webhook inválido")


@app.post("/api/leads")
async def crear_lead(data: LeadInput, request: Request):
    """
    Recibe el formulario de la landing. Es público: lo rellena cualquiera que
    abra la web, y por eso no lleva el WEBHOOK_SECRET (el visitante no lo tiene
    y no se lo podemos dar). A cambio:

      - hay límite de peticiones por IP, para que nadie llene la tabla;
      - hay un campo trampa que los bots rellenan y una persona no;
      - el navegador nunca toca la base de datos, solo esta API.
    """
    if data.web:
        # Honeypot relleno: es un bot. Se responde lo mismo para que no aprenda.
        logger.info("Lead descartado por honeypot (envio automatizado)")
        return {"success": True, "mensaje": "¡Solicitud recibida!"}

    if not _permitido_por_ip(request):
        raise HTTPException(status_code=429,
                            detail="Demasiados envíos desde aquí. Inténtalo en unos minutos.")

    _limpiar_mapa_ips()
    ok, mensaje = await formularios.crear_lead(
        clinica_nombre=data.clinica_nombre.strip(),
        telefono=data.telefono,
        contacto_nombre=data.contacto_nombre,
        especialidad=data.especialidad,
        origen=request.headers.get("referer", "")[:200] or "landing",
    )
    if not ok:
        raise HTTPException(status_code=400, detail=mensaje)
    return {"success": True, "mensaje": mensaje}


@app.post("/api/altas-clinica")
async def registrar_alta_clinica(data: AltaClinicaInput, request: Request):
    """
    Ficha completa de una clínica: servicios, precios, horario e instrucciones.

    Es lo que hace útil al agente. Con la tabla `clinicas` vacía de precios
    reales, la IA tiene que inventarse las tarifas o admitir que no lo sabe, y
    ninguna de las dos cosas sirve.

    No activa la clínica: queda como pendiente hasta revisarla a mano.
    Mismas protecciones que /api/leads, por ser también pública.
    """
    if data.web:
        logger.info("Alta de clinica descartada por honeypot")
        return {"success": True, "mensaje": "¡Recibido!"}

    if not _permitido_por_ip(request):
        raise HTTPException(status_code=429,
                            detail="Demasiados envíos desde aquí. Inténtalo en unos minutos.")

    _limpiar_mapa_ips()
    ok, mensaje = await formularios.registrar_alta_clinica(data.model_dump())
    if not ok:
        raise HTTPException(status_code=400, detail=mensaje)
    return {"success": True, "mensaje": mensaje}


@app.post("/api/llamada-perdida")
async def registrar_llamada_perdida(
    data: LlamadaPerdidaInput,
    background_tasks: BackgroundTasks,
    request: Request,
):
    """
    DISPARADOR 1: Se llama cuando el teléfono de la clínica registra una llamada perdida.
    1. Registra al paciente y crea la conversación en Supabase.
    2. Envía automáticamente el primer mensaje de WhatsApp.
    """
    # Esta ruta dispara un WhatsApp real a un número que elige quien llama, así
    # que va con el mismo secreto que el webhook. La centralita tiene que
    # mandarlo en la cabecera X-Webhook-Secret; sin él la ruta queda cerrada.
    verificar_secreto(request)

    logger.info(f"Llamada perdida recibida de {data.telefono} para clínica {data.clinica_id}")

    # La centralita, la API y los tests escriben el teléfono de forma distinta
    # ("600112233", "34600112233", "+34 600 112 233"). Se fija aquí la forma
    # canónica para que el mismo paciente no acabe con tres fichas distintas.
    telefono = normalizar_telefono(data.telefono)

    # 1. Obtener datos de la clínica
    clinica = await db.get_clinica(data.clinica_id)
    if not clinica:
        raise HTTPException(status_code=404, detail="Clínica no encontrada")

    # 2. Registrar o recuperar paciente
    try:
        paciente = await db.get_or_create_paciente(data.clinica_id, telefono, data.nombre)
    except Exception as e:
        logger.error(f"No se pudo registrar al paciente: {e}")
        raise HTTPException(status_code=502, detail="Error de base de datos al registrar al paciente")

    # 3. Iniciar conversación
    try:
        conversacion = await db.get_or_create_conversacion(data.clinica_id, paciente["id"], origen="llamada_perdida")
    except Exception as e:
        logger.error(f"No se pudo crear la conversación: {e}")
        raise HTTPException(status_code=502, detail="Error de base de datos al crear la conversación")

    # 4. Mensaje inicial personalizado
    nombre_clinica = clinica.get("nombre", "nuestra clínica")
    mensaje_saludo = (
        f"Hola, sentimos no haber podido responder tu llamada en {nombre_clinica}, "
        "estábamos atendiendo a un paciente en consulta. ¿En qué podemos ayudarte? "
        "¿Te gustaría solicitar una cita?"
    )

    # 5. Guardar el mensaje en el historial y enviar por WhatsApp
    await db.guardar_mensaje(conversacion["id"], rol="assistant", contenido=mensaje_saludo)
    background_tasks.add_task(whatsapp.enviar_mensaje, telefono, mensaje_saludo)

    return {
        "success": True,
        "mensaje": "Llamada registrada y WhatsApp enviado",
        "conversacion_id": conversacion["id"],
        "paciente_id": paciente["id"]
    }

async def procesar_mensaje(
    clinica_id: str,
    telefono: str,
    texto_usuario: str,
    background_tasks: BackgroundTasks,
    nombre: Optional[str] = None,
):
    """Lógica compartida del webhook y de la ruta de demo.

    Recibe los datos ya extraídos y normalizados del mensaje entrante.
    """
    logger.info(f"Mensaje entrante de {telefono}: {texto_usuario}")

    # Misma normalización que en la llamada perdida: si el paciente escribió
    # desde un número sin prefijo, tiene que seguir menemukan la conversación
    # que se creó cuando llamó.
    telefono = normalizar_telefono(telefono)

    # 1. Obtener clínica
    clinica = await db.get_clinica(clinica_id)
    if not clinica:
        raise HTTPException(status_code=404, detail="Clínica no encontrada")

    # 2. Obtener paciente y conversación
    try:
        # El nombre que el paciente tiene guardado en WhatsApp sirve para
        # saludarlo por su nombre. Si el paciente ya existe, no se toca.
        paciente = await db.get_or_create_paciente(clinica_id, telefono, nombre)
        conversacion = await db.get_or_create_conversacion(clinica_id, paciente["id"], origen="whatsapp")
    except Exception as e:
        logger.error(f"No se pudo recuperar la conversación: {e}")
        raise HTTPException(status_code=502, detail="Error de base de datos al recuperar la conversación")

    # 3. Guardar el mensaje del usuario
    await db.guardar_mensaje(conversacion["id"], rol="user", contenido=texto_usuario)

    # 4. Obtener los últimos mensajes como contexto
    historial = await db.get_historial(conversacion["id"], limit=8)

    # 5. Generar respuesta con Gemini
    respuesta_ia = await gemini_ai.generar_respuesta(clinica, historial, texto_usuario)

    # 6. Guardar la respuesta y actualizar el estado
    await db.guardar_mensaje(conversacion["id"], rol="assistant", contenido=respuesta_ia)
    await db.actualizar_estado_conversacion(conversacion["id"], nuevo_estado="ia_activa")

    # 7. Enviar la respuesta por WhatsApp
    background_tasks.add_task(whatsapp.enviar_mensaje, telefono, respuesta_ia)

    return {
        "success": True,
        "telefono": telefono,
        "respuesta_generada": respuesta_ia
    }


@app.post("/api/webhook/whatsapp")
async def webhook_whatsapp(payload: Request, background_tasks: BackgroundTasks):
    """
    DISPARADOR 2: Webhook que recibe las respuestas del paciente por WhatsApp.
    1. Verifica el secreto compartido.
    2. Procesa tanto formatos directos como webhooks de Evolution API.
    3. Consulta a Gemini con el contexto de la clínica y responde.
    """
    verificar_secreto(payload)
    body = await payload.json()
    data = body.get("data") or {}

    telefono = None
    texto_usuario = None
    nombre_paciente = None
    clinica_id = CLINICA_DEMO_ID  # Por defecto para la demo

    if "message" in data:
        # Formato Evolution API
        info = extraer_de_evolution(data)
        if info["descartar"]:
            logger.info(f"Webhook ignorado: {info['motivo']}")
            return {"status": "ignored", "motivo": info["motivo"]}

        telefono = info["telefono"]
        texto_usuario = info["texto"]
        nombre_paciente = info["nombre"]

        # Si Evolution no manda el clinica_id, se usa la clínica por defecto.
        # Con una sola instancia por servicio esto basta; para varias clínicas
        # habría que mapear el campo "instance" del evento a un clinica_id.
        clinica_id = body.get("clinica_id", clinica_id) or CLINICA_DEMO_ID

        if not texto_usuario:
            # Nota de voz, foto sin pie, sticker... no hay texto que responder.
            # Gemini se inventaría una transcripción, así que se pide que lo
            # escriban en lugar de fingir que se le ha entendido.
            logger.info(f"Mensaje sin texto de {telefono}; se pide que lo escriba.")
            mensaje_reintentarlo = (
                "Perdona, he recibido tu mensaje pero no he podido entenderlo "
                "(parece un audio o una imagen). ¿Me lo puedes escribir aquí "
                "con unas pocas palabras? Te contesto al momento."
            )
            try:
                await db.get_or_create_paciente(clinica_id, telefono, nombre_paciente)
            except Exception as e:
                logger.warning(f"No se pudo registrar al paciente sin texto: {e}")
            background_tasks.add_task(whatsapp.enviar_mensaje, telefono, mensaje_reintentarlo)
            return {"status": "sin_texto", "telefono": telefono, "respuesta_enviada": True}
    else:
        # Formato directo / de pruebas
        telefono = body.get("telefono")
        texto_usuario = body.get("mensaje")
        clinica_id = body.get("clinica_id", clinica_id)

    if not telefono or not texto_usuario:
        raise HTTPException(status_code=400, detail="Faltan datos de teléfono o mensaje")

    return await procesar_mensaje(clinica_id, telefono, texto_usuario, background_tasks, nombre=nombre_paciente)


@app.post("/api/demo/simular-llamada")
async def demo_simular_llamada(
    request: Request,
    telefono: str = "+34612345678",
    background_tasks: BackgroundTasks = None,
):
    """
    Ruta rápida para la DEMO: Simula una llamada perdida con un solo clic.

    Va tras el mismo secreto que el webhook. Sin esto, cualquiera que supiera
    la URL podía mandar WhatsApps a números ajenos a costa tuya (y gastar la
    cuota de Gemini), que es justo lo que hace esta ruta.
    """
    verificar_secreto(request)

    if background_tasks is None:
        background_tasks = BackgroundTasks()

    data = LlamadaPerdidaInput(
        clinica_id=CLINICA_DEMO_ID,
        telefono=telefono,
        nombre="Paciente Demo"
    )
    return await registrar_llamada_perdida(data, background_tasks, request)


@app.post("/api/demo/mensaje")
async def demo_mensaje(
    request: Request,
    mensaje: str,
    telefono: str = "+34612345678",
    background_tasks: BackgroundTasks = None,
):
    """Simula que el paciente responde por WhatsApp, sin pasar por Evolution API."""
    verificar_secreto(request)

    if background_tasks is None:
        background_tasks = BackgroundTasks()

    return await procesar_mensaje(CLINICA_DEMO_ID, telefono, mensaje, background_tasks)


if __name__ == "__main__":
    import uvicorn
    # En producción manda el Dockerfile (uvicorn directo, sin reload). Este
    # arranque es para desarrollo local, donde sí queremos recargar al guardar.
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=True)
