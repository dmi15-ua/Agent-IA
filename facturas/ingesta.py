"""Paso 1: entrada por correo (IMAP). Descarga los adjuntos PDF/imagen de los mensajes nuevos."""
import email
import imaplib
import re
from datetime import datetime
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr
from pathlib import Path

from . import config


def _limpio(texto: str, defecto: str = "desconocido") -> str:
    """Nombre seguro para usar como carpeta/archivo (sin rutas ni caracteres raros)."""
    t = re.sub(r"[^\w.@+-]+", "_", texto or "").strip("._")
    return t[:80] or defecto


def _nombre_adjunto(parte: Message, ext: str) -> str:
    bruto = parte.get_filename()
    nombre = str(make_header(decode_header(bruto))) if bruto else "factura" + ext
    nombre = Path(nombre).name  # descarta cualquier ruta que venga en el nombre
    return _limpio(nombre) if Path(nombre).suffix else _limpio(nombre) + ext


def guardar_adjuntos(mensaje: Message, destino: Path | None = None) -> list[tuple[Path, str]]:
    """Guarda los adjuntos válidos de un mensaje. Devuelve [(ruta, remitente)]."""
    destino = destino or config.ORIGINALES
    remitente = parseaddr(mensaje.get("From", ""))[1].lower() or "desconocido"
    carpeta = destino / _limpio(remitente)
    sellos = datetime.now().strftime("%Y%m%d-%H%M%S")
    guardados = []
    for n, parte in enumerate(mensaje.walk()):
        ctype = parte.get_content_type()
        if ctype not in config.TIPOS_ADJUNTO or parte.get_content_disposition() not in ("attachment", "inline"):
            continue
        contenido = parte.get_payload(decode=True)
        if not contenido:
            continue
        carpeta.mkdir(parents=True, exist_ok=True)
        ruta = carpeta / f"{sellos}_{n}_{_nombre_adjunto(parte, config.TIPOS_ADJUNTO[ctype])}"
        ruta.write_bytes(contenido)
        guardados.append((ruta, remitente))
    return guardados


def descargar_nuevos() -> list[tuple[Path, str]]:
    """Conecta por IMAP y baja los adjuntos de los correos NO leídos.

    Al pedir el mensaje completo, el servidor lo marca como leído: no se procesa dos veces.
    """
    if not (config.IMAP_USER and config.IMAP_PASSWORD):
        raise RuntimeError("Faltan FACTURAS_IMAP_USER / FACTURAS_IMAP_PASSWORD")
    resultado: list[tuple[Path, str]] = []
    with imaplib.IMAP4_SSL(config.IMAP_HOST) as imap:
        imap.login(config.IMAP_USER, config.IMAP_PASSWORD)
        imap.select(config.IMAP_CARPETA)
        _, ids = imap.search(None, "UNSEEN")
        for num in ids[0].split():
            _, datos = imap.fetch(num, "(RFC822)")
            msg = email.message_from_bytes(datos[0][1])
            resultado += guardar_adjuntos(msg)
    return resultado
