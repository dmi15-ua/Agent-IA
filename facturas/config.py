"""Configuración del agente de facturas. Todo sale de variables de entorno / .env.

Los lectores leen sus propias variables (GEMINI_API_KEY, ANTHROPIC_API_KEY, FACTURAS_MODELO,
FACTURAS_MODELO_GEMINI, FACTURAS_MODELO_OLLAMA, OLLAMA_HOST). Importar este módulo carga el .env.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# local | ollama | gemini | claude | simulado
#   local y ollama: la factura NO sale de vuestro equipo. gemini y claude: se envía a la API.
LECTOR = os.getenv("FACTURAS_LECTOR", "local")

# --- Carpetas y ficheros ----------------------------------------------------
DATOS = Path(os.getenv("FACTURAS_DATOS", "facturas_datos"))
ORIGINALES = DATOS / "originales"        # copia del adjunto tal cual llegó, por remitente
BASE_DATOS = DATOS / "facturas.db"       # SQLite: fuente de verdad (facturas y cuentas por proveedor)
REVISION = DATOS / "revision.csv"        # vista de la base para que el gestor trabaje en Excel
IMPORTACION = DATOS / "importacion.csv"  # salida para el programa de contabilidad

# --- Correo (IMAP) ----------------------------------------------------------
IMAP_HOST = os.getenv("FACTURAS_IMAP_HOST", "imap.gmail.com")
IMAP_USER = os.getenv("FACTURAS_IMAP_USER", "")
IMAP_PASSWORD = os.getenv("FACTURAS_IMAP_PASSWORD", "")  # contraseña de aplicación
IMAP_CARPETA = os.getenv("FACTURAS_IMAP_CARPETA", "INBOX")

TIPOS_ADJUNTO = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

# --- Cuentas contables ------------------------------------------------------
# Veces seguidas que un humano debe confirmar la misma cuenta de un proveedor antes de que el
# sistema deje de marcar la factura para revisión por ese motivo.
CONFIRMACIONES_CUENTA = int(os.getenv("FACTURAS_CONFIRMACIONES_CUENTA", "3"))
