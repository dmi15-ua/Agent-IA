"""Une los pasos: archivo -> lector -> comprobaciones -> duplicados -> hoja de revisión."""
import logging
from datetime import datetime
from pathlib import Path

from . import config, hoja
from .extraccion.procesar import archivos_de, procesar_archivo as leer_archivo
from .extraccion.proveedor import Proveedor, crear_proveedor

logger = logging.getLogger(__name__)


def procesar_archivo(ruta: Path, remitente: str, proveedor: Proveedor, ruta_hoja: Path | None = None) -> dict:
    """Procesa UNA factura y la deja en la hoja. Si algo falla queda como `error`, nunca se pierde."""
    lectura = leer_archivo(ruta, proveedor)
    fila = hoja.fila_desde(lectura, remitente, ruta, datetime.now().isoformat(timespec="seconds"))
    return hoja.anadir(fila, ruta_hoja)


def expandir(rutas: list[Path]) -> list[Path]:
    """Archivos sueltos tal cual; las carpetas, con las facturas que contienen."""
    salida: list[Path] = []
    for r in rutas:
        salida += archivos_de(r) if r.is_dir() else [r]
    return salida


def procesar_rutas(rutas: list[Path], remitente: str = "", lector: str | None = None) -> list[dict]:
    proveedor = crear_proveedor(lector or config.LECTOR)
    return [procesar_archivo(r, remitente, proveedor) for r in expandir(rutas)]


def procesar_correo(lector: str | None = None) -> list[dict]:
    from . import ingesta

    proveedor = crear_proveedor(lector or config.LECTOR)
    return [procesar_archivo(r, rem, proveedor) for r, rem in ingesta.descargar_nuevos()]
