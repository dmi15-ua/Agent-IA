import logging
import httpx
from typing import Dict, Any
import config

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
        # Limpieza básica del número (remover espacios, guiones, símbolos)
        numero_limpio = "".join(filter(str.isdigit, telefono))

        if not self.api_url:
            print("\n" + "="*50)
            print("📱 [SIMULADOR DE WHATSAPP - MENSAJE SALIENTE]")
            print(f"Para: {telefono} ({numero_limpio})")
            print(f"Mensaje: {texto}")
            print("="*50 + "\n")
            return True

        # Conector para Evolution API (uno de los conectores QR de código abierto más populares)
        headers = {
            "apikey": self.api_key,
            "Content-Type": "application/json"
        }
        payload = {
            "number": numero_limpio,
            "text": texto
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.api_url}/message/sendText/{self.instance}",
                    headers=headers,
                    json=payload
                )
                if resp.status_code in (200, 201):
                    logger.info(f"Mensaje de WhatsApp enviado a {telefono}")
                    return True
                else:
                    logger.error(f"Error al enviar WhatsApp ({resp.status_code}): {resp.text}")
                    return False
        except Exception as e:
            logger.error(f"Excepción al enviar WhatsApp: {e}")
            return False

whatsapp = WhatsAppService()
