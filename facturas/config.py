"""Configuración del agente de facturas. Todo sale de variables de entorno / .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- Modelo de visión -------------------------------------------------------
# "gemini" | "claude" | "simulado" (lee un .json junto a la factura; sin API ni coste)
EXTRACTOR = os.getenv("FACTURAS_EXTRACTOR", "gemini")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
FACTURAS_GEMINI_MODEL = os.getenv("FACTURAS_GEMINI_MODEL", "gemini-3.5-flash-lite")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
FACTURAS_CLAUDE_MODEL = os.getenv("FACTURAS_CLAUDE_MODEL", "claude-haiku-5-5")

TIMEOUT_API = float(os.getenv("FACTURAS_TIMEOUT_API", "90"))

# --- Carpetas y ficheros ----------------------------------------------------
DATOS = Path(os.getenv("FACTURAS_DATOS", "facturas_datos"))
ORIGINALES = DATOS / "originales"      # copia del adjunto tal cual llegó, por remitente
REVISION = DATOS / "revision.csv"      # la "hoja" que revisa el gestor
IMPORTACION = DATOS / "importacion.csv"  # salida para el programa de contabilidad

# --- Correo (IMAP) ----------------------------------------------------------
IMAP_HOST = os.getenv("FACTURAS_IMAP_HOST", "imap.gmail.com")
IMAP_USER = os.getenv("FACTURAS_IMAP_USER", "")
IMAP_PASSWORD = os.getenv("FACTURAS_IMAP_PASSWORD", "")  # contraseña de aplicación
IMAP_CARPETA = os.getenv("FACTURAS_IMAP_CARPETA", "INBOX")

# --- Validaciones -----------------------------------------------------------
# Diferencia máxima (céntimos) entre la cuota que declara la factura y base*tipo.
# Las facturas con varias líneas redondean por línea y se desvían un par de céntimos.
TOLERANCIA_CUOTA_CENT = int(os.getenv("FACTURAS_TOLERANCIA_CUOTA_CENT", "2"))
TIPOS_IVA_VALIDOS = (0, 4, 10, 21)

TIPOS_ADJUNTO = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
