import os
from dotenv import load_dotenv

# Cargar variables del archivo .env si existe
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# Modelos en orden de preferencia: si el primero falla, se intenta el siguiente.
GEMINI_MODELS = [
    m.strip()
    for m in os.getenv("GEMINI_MODELS", "gemini-2.5-flash,gemini-2.5-flash-lite").split(",")
    if m.strip()
]

# Presupuesto de salida. Los modelos flash reservan parte de estos tokens para
# razonar en silencio, así que un valor bajo hace que la respuesta visible se
# corte a media frase. 1024 deja margen de sobra para un mensaje de WhatsApp.
GEMINI_MAX_OUTPUT_TOKENS = int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "1024"))

# Desactivar el razonamiento interno (0 = sin pensamiento).
# Para responder WhatsApp no aporta nada y encarece la respuesta.
GEMINI_THINKING_BUDGET = int(os.getenv("GEMINI_THINKING_BUDGET", "0"))

# Secreto compartido con la centralita / Evolution API para poder autenticar
# las llamadas entrantes. Si se deja vacío, los endpoints NO aceptan peticiones
# externas (ver webhook_guard en main.py).
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

# Configuración de WhatsApp
WHATSAPP_API_URL = os.getenv("WHATSAPP_API_URL", "")
WHATSAPP_API_KEY = os.getenv("WHATSAPP_API_KEY", "")
WHATSAPP_INSTANCE_NAME = os.getenv("WHATSAPP_INSTANCE_NAME", "clinica_demo")

# Servidor
PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "0.0.0.0")
