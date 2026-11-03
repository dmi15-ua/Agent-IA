"""Une los pasos: archivo -> (¿ya leído?) -> lector -> comprobaciones -> cuenta -> duplicados -> base de datos."""
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import config
from .almacen import REPETIDA, REVISAR, Almacen, fila_desde, hash_de
from .extraccion.modelos import ERROR
from .extraccion.procesar import archivos_de, procesar_archivo as leer_archivo
from .extraccion.proveedor import Proveedor, crear_proveedor

Progreso = Callable[[int, int, Path], None]


def procesar_archivo(ruta: Path, remitente: str, proveedor: Proveedor, almacen: Almacen, reprocesar: bool = False) -> dict:
    """Procesa UNA factura y la guarda. Si algo falla queda como `error`, nunca se pierde."""
    h = hash_de(ruta) if ruta.is_file() else ""
    if h and not reprocesar and (orig := almacen.por_hash(h)):
        # El mismo archivo ya se leyó: no se vuelve a llamar al lector (ahorra tiempo y coste de API).
        fila = {"recibida": datetime.now().isoformat(timespec="seconds"), "remitente": remitente, "archivo": str(ruta), "hash": h, "estado": REPETIDA,
                "a_revisar": f"Mismo archivo que la factura #{orig['id']} (ya leída, no se vuelve a procesar)",
                "original_id": orig["id"]}
        return almacen.guardar(fila)

    lectura = leer_archivo(ruta, proveedor)
    fila = fila_desde(lectura, remitente, ruta, h)
    if lectura.estado != ERROR:
        cuenta, estado_cuenta, motivo = almacen.proponer_cuenta(fila["nif_proveedor"])
        fila["cuenta_contable"], fila["cuenta_estado"] = cuenta, estado_cuenta
        if estado_cuenta in ("nueva", "dudosa"):
            fila["estado"] = REVISAR
            fila["a_revisar"] = f"{fila['a_revisar']} | cuenta_contable: {motivo}".strip(" |")
    return almacen.guardar(fila)


def expandir(rutas: list[Path]) -> list[Path]:
    """Archivos sueltos tal cual; las carpetas, con las facturas que contienen."""
    salida: list[Path] = []
    for r in rutas:
        salida += archivos_de(r) if r.is_dir() else [r]
    return salida


def procesar_rutas(rutas: list[Path], almacen: Almacen, remitente: str = "", lector: str | None = None,
                   reprocesar: bool = False, progreso: Progreso | None = None) -> list[dict]:
    proveedor = crear_proveedor(lector or config.LECTOR)
    archivos = expandir(rutas)
    filas = []
    for i, r in enumerate(archivos, 1):
        if progreso:
            progreso(i, len(archivos), r)
        filas.append(procesar_archivo(r, remitente, proveedor, almacen, reprocesar))
    return filas


def procesar_correo(almacen: Almacen, lector: str | None = None, progreso: Progreso | None = None) -> list[dict]:
    from . import ingesta

    proveedor = crear_proveedor(lector or config.LECTOR)
    descargados = ingesta.descargar_nuevos()
    filas = []
    for i, (r, rem) in enumerate(descargados, 1):
        if progreso:
            progreso(i, len(descargados), r)
        filas.append(procesar_archivo(r, rem, proveedor, almacen))
    return filas


def pasada_vigilancia(carpeta: Path, almacen: Almacen, proveedor: Proveedor, vistos: dict, remitente: str = "",
                      estable_segundos: float = 2.0, progreso: Progreso | None = None) -> list[dict]:
    """Procesa los archivos nuevos de la carpeta. `vistos` recuerda (nombre, tamaño, fecha) entre pasadas.

    Se salta lo modificado hace menos de `estable_segundos`: puede estar aún copiándose.
    """
    nuevos = []
    for r in archivos_de(carpeta):
        st = r.stat()
        firma = (r.name, st.st_size, st.st_mtime_ns)
        if vistos.get(r.name) == firma or time.time() - st.st_mtime < estable_segundos:
            continue
        nuevos.append((r, firma))
    filas = []
    for i, (r, firma) in enumerate(nuevos, 1):
        if progreso:
            progreso(i, len(nuevos), r)
        filas.append(procesar_archivo(r, remitente, proveedor, almacen))
        vistos[r.name] = firma
    return filas


def vigilar(carpeta: Path, almacen: Almacen, lector: str | None = None, cada: float = 10.0, remitente: str = "",
            progreso: Progreso | None = None, alprocesar: Callable[[list[dict]], None] | None = None,
            continuar: Callable[[], bool] = lambda: True) -> None:
    """Procesa lo que va llegando a la carpeta, hasta Ctrl+C. Lo ya leído (mismo hash) no se repite."""
    proveedor = crear_proveedor(lector or config.LECTOR)
    vistos: dict = {}
    while continuar():
        filas = pasada_vigilancia(carpeta, almacen, proveedor, vistos, remitente, progreso=progreso)
        if filas and alprocesar:
            alprocesar(filas)
        time.sleep(cada)
