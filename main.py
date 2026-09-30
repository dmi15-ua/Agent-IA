import logging
import os
import secrets

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Optional

import config
from database import db
from gemini_service import gemini_ai
from whatsapp_service import whatsapp

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


CLINICA_DEMO_ID = "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"


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


@app.post("/api/llamada-perdida")
async def registrar_llamada_perdida(data: LlamadaPerdidaInput, background_tasks: BackgroundTasks):
    """
    DISPARADOR 1: Se llama cuando el teléfono de la clínica registra una llamada perdida.
    1. Registra al paciente y crea la conversación en Supabase.
    2. Envía automáticamente el primer mensaje de WhatsApp.
    """
    logger.info(f"Llamada perdida recibida de {data.telefono} para clínica {data.clinica_id}")

    # 1. Obtener datos de la clínica
    clinica = await db.get_clinica(data.clinica_id)
    if not clinica:
        raise HTTPException(status_code=404, detail="Clínica no encontrada")

    # 2. Registrar o recuperar paciente
    try:
        paciente = await db.get_or_create_paciente(data.clinica_id, data.telefono, data.nombre)
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
    background_tasks.add_task(whatsapp.enviar_mensaje, data.telefono, mensaje_saludo)

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
):
    """Lógica compartida del webhook y de la ruta de demo.

    Recibe los datos ya extraídos y normalizados del mensaje entrante.
    """
    logger.info(f"Mensaje entrante de {telefono}: {texto_usuario}")

    # 1. Obtener clínica
    clinica = await db.get_clinica(clinica_id)
    if not clinica:
        raise HTTPException(status_code=404, detail="Clínica no encontrada")

    # 2. Obtener paciente y conversación
    try:
        paciente = await db.get_or_create_paciente(clinica_id, telefono)
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

    # Extraer teléfono y mensaje (soporta formato simplificado y formato Evolution API)
    telefono = None
    texto_usuario = None
    clinica_id = CLINICA_DEMO_ID  # Por defecto para la demo

    if "data" in body and "message" in body.get("data", {}):
        # Formato Evolution API
        key = body["data"].get("key", {})

        # Evitar responder a mensajes enviados por el propio bot (provocaría bucle)
        if key.get("fromMe", False):
            return {"status": "ignored_self_message"}

        remote_jid = key.get("remoteJid", "")
        telefono = remote_jid.split("@")[0]
        texto_usuario = (
            body["data"]["message"].get("conversation")
            or body["data"]["message"].get("extendedTextMessage", {}).get("text", "")
        )

        # En producción, Evolution API debe enviar el clinica_id en el cuerpo.
        # Si no lo manda, se usa la clínica por defecto.
        clinica_id = body.get("clinica_id", clinica_id) or CLINICA_DEMO_ID
    else:
        # Formato directo / de pruebas
        telefono = body.get("telefono")
        texto_usuario = body.get("mensaje")
        clinica_id = body.get("clinica_id", clinica_id)

    if not telefono or not texto_usuario:
        raise HTTPException(status_code=400, detail="Faltan datos de teléfono o mensaje")

    return await procesar_mensaje(clinica_id, telefono, texto_usuario, background_tasks)


@app.post("/api/demo/simular-llamada")
async def demo_simular_llamada(telefono: str = "+34612345678", background_tasks: BackgroundTasks = None):
    """
    Ruta rápida para la DEMO: Simula una llamada perdida con un solo clic.
    Solo para desarrollo; en producción debe ir tras autenticación.
    """
    if background_tasks is None:
        background_tasks = BackgroundTasks()

    data = LlamadaPerdidaInput(
        clinica_id=CLINICA_DEMO_ID,
        telefono=telefono,
        nombre="Paciente Demo"
    )
    return await registrar_llamada_perdida(data, background_tasks)


@app.post("/api/demo/mensaje")
async def demo_mensaje(
    mensaje: str,
    telefono: str = "+34612345678",
    background_tasks: BackgroundTasks = None,
):
    """Simula que el paciente responde por WhatsApp, sin pasar por Evolution API."""
    if background_tasks is None:
        background_tasks = BackgroundTasks()

    return await procesar_mensaje(CLINICA_DEMO_ID, telefono, mensaje, background_tasks)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=True)
