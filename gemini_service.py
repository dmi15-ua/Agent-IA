import logging
import httpx
from typing import List, Dict, Any, Optional
import config

logger = logging.getLogger(__name__)

# Errores que justifican probar con OTRO modelo.
#   404 = ese modelo ya no existe
#   5xx  = incidencia del servicio (puede ser solo de un modelo)
CODIGOS_REINTENTABLES = {404, 500, 502, 503, 504}

# La cuota NO se aplica por modelo sino por proyecto (ver docs de Google:
# "Rate limits are applied per project, not per API key"). Si nos dicen 429,
# probar con otro modelo solo gasta peticiones y vuelve a fallar. Se para ya.
CUOTA_AGOTADA = 429

# 400 = la API no acepta lo que le hemos mandado. El caso real es el bloque
# thinkingConfig, que los Gemini 3.x rechazan siempre, incluso con
# thinkingBudget=0. No es un problema del modelo, así que no se pasa al
# siguiente de la lista: se reintenta sin ese bloque.
PARAMETRO_INVALIDO = 400

# ÚNICO finishReason que confirma que la respuesta se cortó de verdad. Cualquier
# otro (STOP, SAFETY...) significa que el modelo llegó a terminar su texto.
CORTADO_POR_TOKENS = "MAX_TOKENS"

# Puntuación que delata un corte. Solo se consulta cuando la API no devuelve
# finishReason, porque en un mensaje de WhatsApp es perfectamente normal
# terminar sin ella ("vale, nos vemos", "son 45 euros").
FINALES_ESPERADOS = (".", "?", "!", '"', ")", "€", "…", ":", ";")


def _esta_incompleta(texto: str, finish: Optional[str]) -> bool:
    """True solo si la respuesta está realmente cortada y merece otro intento.

    Antes se deducía únicamente de que el texto no acabase en signo de
    puntuación. Eso descartaba respuestas perfectamente buenas: en WhatsApp
    casi nadie puntúa, así que "Lucho" o "Vale, estad al día" se tylaban,
    se gastaba un reintento, caía al modelo de respaldo y el paciente
    recibía el mensaje de "tengo un problema técnico".

    Con finishReason=STOP el modelo terminó bien, así que el texto se acepta
    siempre. Solo MAX_TOKENS justifica volver a pedir más tokens.
    """
    limpio = texto.strip()
    if not limpio:
        return True
    if finish == CORTADO_POR_TOKENS:
        return True
    if finish:
        # La API confirma que terminó: el texto es válido aunque no cierre en
        # punto, y descartar una respuesta buena solo cuesta otro reintento.
        return False
    # finishReason ausente o desconocido: solo aquí el final da alguna pista.
    return not limpio.endswith(FINALES_ESPERADOS)

class GeminiService:
    def __init__(self):
        self.api_key = config.GEMINI_API_KEY
        self.modelos = config.GEMINI_MODELS
        self.base_url = "https://generativelanguage.googleapis.com/v1beta/models"

    @property
    def endpoint(self) -> str:
        """Endpoint del modelo preferido (se mantiene por compatibilidad)."""
        return f"{self.base_url}/{self.modelos[0]}:generateContent" if self.modelos else ""

    async def generar_respuesta(self, clinica: Dict[str, Any], historial: List[Dict[str, str]], mensaje_usuario: str) -> str:
        """
        Genera una respuesta con la API de Google Gemini, enriquecida con el
        contexto específico de la clínica y el historial de chat.

        Si el modelo preferido falla, se prueban los siguientes de config.GEMINI_MODELS.
        """
        if not self.api_key:
            logger.warning("GEMINI_API_KEY no configurada. Devolviendo respuesta simulada.")
            return (
                f"¡Hola! Soy Laura de {clinica.get('nombre', 'la clínica')}. "
                "Disculpa no haber podido atender tu llamada antes. "
                "¿Te gustaría que te reservemos una cita de valoración o tienes alguna duda específica?"
            )

        # 1. Construir las instrucciones del sistema con los datos de la clínica
        prompt_sistema = clinica.get("prompt_sistema") or "Eres el asistente de la clínica. Atiende con amabilidad y resuelve dudas."
        contexto_clinica = f"""
DATOS DE LA CLÍNICA:
- Nombre: {clinica.get('nombre', 'Clínica')}
- Horario: {clinica.get('horario', 'Consultar horario')}
- Dirección: {clinica.get('direccion', 'Consultar ubicación')}
- Servicios y Tarifas:
{clinica.get('servicios', 'Consulta los tratamientos en recepción.')}

ESTA ES TODA LA INFORMACIÓN QUE TIENES SOBRE LA CLÍNICA. No hay nada más.

INSTRUCCIONES DE COMPORTAMIENTO:
{prompt_sistema}

REGLA MÁS IMPORTANTE: NO INVENTES NUNCA DATOS
- Todo lo que afirmes debe estar escrito literalmente en la información de arriba
  o en los mensajes del paciente.
- Si te preguntan algo que NO aparece ahí (si hay parking, si aceptan un seguro
  concreto, si hay acceso para silla de ruedas, si atienden a menores, si hacen
  financiación, etc.), NO lo respondas por tu cuenta. NI afirmando NI negando.
- Prohibido responder "sí" o "no" a algo que no esté en los datos. Decir que no
  también es inventar: "no tenemos parking" es tan falso como "sí tenemos parking".
- La respuesta correcta ante un dato desconocido es: "Lo compruebo con el equipo y
  te confirmo", o "¿prefieres que te lo confirmemos por teléfono?".
- Si no estás segura de si un dato está o no en la información, trátalo como desconocido.
- Ejemplos correctos: "No tengo ese dato, se lo confirmo al equipo", "Eso lo verifica
  recepción cuando te agende la cita".
- Ejemplos prohibidos: "no aceptan ese seguro" (no lo sabes), "no tenemos parking"
  (no lo sabes), "ese tratamiento no existe" (no lo sabes).

OTRAS RESTRICCIONES:
- NUNCA inventes datos médicos ni hagas diagnósticos. No digas si algo es grave,
  si un tratamiento sirve o no, ni qué resultados tendrá.
- NUNCA prometas descuentos, financiación, precios fuera de la lista ni plazos.
- Si te piden un dato clínico, encamina a la cita de valoración: el profesional lo verá allí.

REGLAS DE FORMATO:
- Responde siempre como mensaje de WhatsApp: tono cercano, natural, empático y MUY breve (1-3 frases).
- Nunca respondas con bloques largos de texto ni listas interminables.
- Busca siempre avanzar la conversación hacia agendar una cita o pedir nombre y horario.
"""

        # 2. Convertir el historial al formato contents de Gemini API
        contents = []
        for msg in historial:
            role = "user" if msg["rol"] == "user" else "model"
            contents.append({
                "role": role,
                "parts": [{"text": msg["contenido"]}]
            })

        # El webhook ya guarda el mensaje entrante en la base de datos antes de
        # llamar a este método, así que puede venir ya en el historial. Solo lo
        # añadimos si no está, para no duplicarlo en el contexto.
        ya_esta = (
            contents
            and contents[-1]["role"] == "user"
            and contents[-1]["parts"][0]["text"].strip() == mensaje_usuario.strip()
        )
        if not ya_esta:
            contents.append({
                "role": "user",
                "parts": [{"text": mensaje_usuario}]
            })

        if not self.modelos:
            logger.error("No hay ningún modelo de Gemini configurado (GEMINI_MODELS vacío).")
            return self._respuesta_de_fallback(clinica)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                ultimo_error = "sin respuesta"

                for modelo in self.modelos:
                    endpoint = f"{self.base_url}/{modelo}:generateContent"

                    # Tresattempt por modelo:
                    #   1. el normal, con el presupuesto de razonamiento que toque
                    #   2. el mismo SIN el bloque thinkingConfig
                    #   3. el doble de tokens de salida, por si la respuesta sale cortada
                    #
                    # El intento 2 existe porque los Gemini 3.x (3.5-flash-lite y
                    # familia) rechazan con HTTP 400 cualquier bloque thinkingConfig,
                    # incluido thinkingBudget=0. Como no hay forma de saber de
                    # antemano que modelo hay detrás, se deduce del 400 y se reintenta
                    # sin el bloque en el mismo modelo, en vez de spends de un 400
                    # al siguiente de la lista.
                    if config.GEMINI_THINKING_BUDGET is None:
                        intentos = [
                            (config.GEMINI_MAX_OUTPUT_TOKENS, None),
                            (config.GEMINI_MAX_OUTPUT_TOKENS * 2, None),
                        ]
                    else:
                        intentos = [
                            (config.GEMINI_MAX_OUTPUT_TOKENS, config.GEMINI_THINKING_BUDGET),
                            (config.GEMINI_MAX_OUTPUT_TOKENS, None),
                            (config.GEMINI_MAX_OUTPUT_TOKENS * 2, None),
                        ]

                    for num_intento, (max_tokens, thinking_budget) in enumerate(intentos, start=1):
                        generation_config = {
                            "temperature": 0.5,
                            "maxOutputTokens": max_tokens,
                        }
                        if thinking_budget is not None:
                            generation_config["thinkingConfig"] = {"thinkingBudget": thinking_budget}

                        payload = {
                            "system_instruction": {
                                "parts": [{"text": contexto_clinica}]
                            },
                            "contents": contents,
                            "generationConfig": generation_config,
                        }

                        try:
                            response = await client.post(
                                f"{endpoint}?key={self.api_key}",
                                json=payload
                            )
                        except Exception as e:
                            logger.warning(f"Fallo de red con el modelo {modelo}: {e}")
                            ultimo_error = str(e)
                            break  # otro modelo, otro intento

                        if response.status_code == 200:
                            data = response.json()
                            candidates = data.get("candidates", [])
                            finish = candidates[0].get("finishReason") if candidates else None
                            text = ""
                            if candidates:
                                text = "".join(
                                    p.get("text", "")
                                    for p in candidates[0].get("content", {}).get("parts", [])
                                ).strip()

                            if text and not _esta_incompleta(text, finish):
                                logger.info(
                                    f"Respuesta generada con {modelo} "
                                    f"(intento {num_intento}, finishReason={finish})"
                                )
                                return text

                            if text:
                                # Hay texto pero está cortado: el presupuesto de
                                # salida se agotó (MAX_TOKENS). Vale la pena
                                # pedir más tokens una vez.
                                logger.warning(
                                    f"Respuesta incompleta de {modelo} "
                                    f"(finishReason={finish}). Reintentando con más tokens."
                                )
                                ultimo_error = f"respuesta incompleta ({finish})"
                                continue  # siguiente intento de presupuesto

                            # 200 pero sin texto: bloqueado por seguridad, o vacío.
                            logger.warning(
                                f"Gemini ({modelo}) sin texto utilizable. finishReason={finish}"
                            )
                            ultimo_error = f"respuesta vacía ({finish})"
                            break

                        cuerpo = response.text[:300]
                        ultimo_error = f"HTTP {response.status_code}: {cuerpo}"

                        if response.status_code == PARAMETRO_INVALIDO and thinking_budget is not None:
                            # Solo se acepta si veníamos mandando thinkingConfig: el
                            # modelo lo ha rechazado y el siguiente intento ya lo
                            # quita. Un 400 sin thinkingConfig es otra cosa.
                            logger.warning(
                                f"{modelo} rechazó el bloque thinkingConfig (400). "
                                "Reintentando el mismo modelo sin él."
                            )
                            ultimo_error = "HTTP 400 (thinkingConfig rechazado)"
                            continue

                        if response.status_code == PARAMETRO_INVALIDO:
                            logger.error(
                                f"Gemini ({modelo}) rechazó la petición (400) y ya se "
                                f"había enviado sin thinkingConfig: {cuerpo}"
                            )
                            return self._respuesta_de_fallback(clinica)

                        if response.status_code == CUOTA_AGOTADA:
                            # La cuota es del proyecto, no del modelo: insistir con
                            # otro gastaría peticiones sin ninguna posibilidad de éxito.
                            logger.error(
                                "Cuota de Gemini agotada. Se detiene sin probar más modelos. "
                                "Revisa tu plan en aistudio.google.com/rate-limit."
                            )
                            return self._respuesta_de_fallback(clinica)

                        if response.status_code in CODIGOS_REINTENTABLES:
                            logger.warning(
                                f"El modelo {modelo} falló ({response.status_code}). "
                                "Probando con el siguiente modelo de la lista."
                            )
                            break  # otro modelo

                        logger.error(f"Error no recuperable en Gemini ({modelo}): {cuerpo}")
                        return self._respuesta_de_fallback(clinica)

                logger.error(f"Sin respuesta de Gemini. Último error: {ultimo_error}")

        except Exception as e:
            logger.error(f"Excepción al conectar con Gemini: {e}")

        return self._respuesta_de_fallback(clinica)

    @staticmethod
    def _respuesta_de_fallback(clinica: Dict[str, Any]) -> str:
        """Respuesta de emergencia si la IA no está disponible.

        Se usa el teléfono de la clínica para que el paciente tenga siempre una
        vía humana, en lugar de quedarse sin respuesta.
        """
        return (
            f"Hola, soy el asistente de {clinica.get('nombre', 'la clínica')}. "
            "Ahora mismo tengo un problema técnico para responderte. "
            "¿Puedes llamarnos de nuevo en un momento? Disculpa las molestias."
        )

gemini_ai = GeminiService()
