import logging
import httpx
from typing import Dict, Any
import config
from utils import normalizar_telefono

logger = logging.getLogger(__name__)

class WhatsAppService:
    def __init__(self):
        self.api_url = config.WHATSAPP_API_URL.rstrip("/")
        self.api_key = config.WHATSAPP_API_KEY
        self.instance = config.WHATSAPP_INSTANCE_NAME

    async def enviar_mensaje(self, telefono: str, texto: str) -> bool:
        """
        Envía un mensaje de WhatsApp al número especificado.
        Si no hay API configurada, funciona en modo SIMULACIÓN (ideal para pruebas locales).
        """
        # Se normaliza igual que en la base de datos y luego se quita el "+":
        # Evolution API espera solo dígitos, y así el número que sale es
        # exactamente el mismo que se guardó como paciente.
        numero_limpio = normalizar_telefono(telefono).lstrip("+")

        if not self.api_url:
            print("\n" + "="*50)
            print("📱 [SIMULADOR DE WHATSAPP - MENSAJE SALIENTE]")
            print(f"Para: {telefono} ({numero_limpio})")
            print(f"Mensaje: {texto}")
            print("="*50 + "\n")
            return True

        # Conector para Evolution API (Baileys), uno de los conectores de QR
        # más populares. El contrato {number, text} contra
        # /message/sendText/{instance} es el de la v2: en la v3 cambiaron las
        # rutas y los nombres de campo, así que la imagen debe ir fijada a 2.3.x.
        headers = {
            "apikey": self.api_key,
            "Content-Type": "application/json"
        }
        payload = {
            "number": numero_limpio,
            "text": texto
        }

        # El timeout de 10 s era demasiado corto. Baileys necesita tiempo para
        # cifrar, subir las claves y registrar el mensaje; hay casos reportados
        # de envíos que tardan más de 30 s. Con 10 s cortábamos a mitad de un
        # mensaje que sí iba a llegar, y el paciente se quedaba sin respuesta
        # sin que nadie entendiera por qué.
        #
        # Se reintenta una vez solo ante error de red o 5xx. Un 4xx (número
        # inválido, JID que no es respondible) no mejora al repetir, así que se
        # devuelve el fallo directamente en lugar de gastar otro intento.
        for intento in range(1, 3):
            try:
                async with httpx.AsyncClient(timeout=45.0) as client:
                    resp = await client.post(
                        f"{self.api_url}/message/sendText/{self.instance}",
                        headers=headers,
                        json=payload
                    )

                    if resp.status_code in (200, 201):
                        logger.info(f"Mensaje de WhatsApp enviado a {telefono}")
                        return True

                    if 400 <= resp.status_code < 500:
                        logger.error(
                            f"WhatsApp rechazo el envio a {telefono} "
                            f"({resp.status_code}): {resp.text[:300]}"
                        )
                        return False

                    logger.warning(
                        f"Fallo transitorio al enviar WhatsApp a {telefono} "
                        f"({resp.status_code}), intento {intento}/2."
                    )

            except Exception as e:
                logger.warning(
                    f"Error de red enviando a {telefono}, intento {intento}/2: {e}"
                )

        logger.error(f"No se pudo enviar el WhatsApp a {telefono} tras 2 intentos.")
        return False

whatsapp = WhatsAppService()
