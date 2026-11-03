"""Une los pasos: archivo -> modelo -> validaciones -> duplicados -> hoja."""
import logging
from datetime import datetime
from pathlib import Path

from . import extraccion, hoja, validacion
from .modelos import CAMPOS_MODELO, REVISAR

logger = logging.getLogger(__name__)


def procesar_archivo(ruta: Path, remitente: str = "", extractor: str | None = None, ruta_hoja: Path | None = None) -> dict:
    """Procesa UNA factura y la deja en la hoja. Un fallo no se pierde: queda como `revisar`."""
    try:
        leido = extraccion.extraer(ruta, extractor)
        fila = validacion.validar(leido)
    except extraccion.ErrorExtraccion as e:
        logger.warning("No se pudo leer %s: %s", ruta.name, e)
        fila = {c: "" for c in CAMPOS_MODELO}
        fila.update(estado=REVISAR, motivos=f"No se pudo leer la factura: {e}", clave="")
    fila.update(
        recibida=datetime.now().isoformat(timespec="seconds"),
        remitente=remitente,
        archivo=str(ruta),
    )
    return hoja.anadir(fila, ruta_hoja)


def procesar_correo(extractor: str | None = None) -> list[dict]:
    from . import ingesta

    return [procesar_archivo(r, rem, extractor) for r, rem in ingesta.descargar_nuevos()]
