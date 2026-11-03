"""Hoja de revisión (CSV): una VISTA de la base de datos para trabajar en Excel / Google Sheets.

Flujo del gestor:
  1. `python -m facturas hoja`        escribe revision.csv desde la base.
  2. En Excel: filtra por estado=revisar, mira `a_revisar`, corrige datos, pone la `cuenta_contable`
     y cambia el estado a `confirmada`.
  3. `python -m facturas sincronizar` lee la hoja y guarda los cambios en la base. Al confirmar una
     factura con cuenta, el sistema aprende la cuenta de ese proveedor.
  4. `python -m facturas exportar`    genera el CSV de importación con las confirmadas.

CSV con delimitador `;` y UTF-8 con BOM para que Excel en español lo abra bien.
"""
import csv
from pathlib import Path

from . import config
from .almacen import CAMPOS, CONFIRMADA, EDITABLES, LISTA, Almacen
from .extraccion.modelos import CAMPOS_NUMERO

DELIM = ";"
ESTADOS = {"lista", "revisar", "error", "repetida", "confirmada"}

COLUMNAS_HOJA = (
    "id", "recibida", "remitente", "archivo", "estado", "a_revisar", "error", "que_hacer",
    *CAMPOS, "cuenta_contable", "cuenta_estado", "original_id",
)

# Columnas del CSV de importación. Adaptadlas al formato que pida el programa de
# contabilidad (A3, Contasol, Holded, Sage...). Importes con coma decimal.
COLUMNAS_IMPORTACION = (
    ("fecha_expedicion", "Fecha"),
    ("numero_factura", "NumFactura"),
    ("nif_proveedor", "NIF"),
    ("proveedor", "Proveedor"),
    ("cuenta_contable", "Cuenta"),
    ("base_imponible", "Base"),
    ("cuota_iva", "CuotaIVA"),
    ("retencion_irpf", "RetencionIRPF"),
    ("total", "Total"),
)
NUMERICAS = set(CAMPOS_NUMERO)


def _escribir(ruta: Path, cabecera, filas) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=DELIM)
        w.writerow(cabecera)
        w.writerows(filas)
    tmp.replace(ruta)  # escritura atómica: nunca queda el archivo a medias


def escribir_hoja(almacen: Almacen, ruta: Path | None = None) -> int:
    ruta = ruta or config.REVISION
    filas = almacen.listar()
    _escribir(ruta, COLUMNAS_HOJA, ([("" if f[c] is None else f[c]) for c in COLUMNAS_HOJA] for f in filas))
    return len(filas)


def sincronizar(almacen: Almacen, ruta: Path | None = None) -> dict:
    """Aplica a la base lo que el gestor cambió en la hoja. Devuelve un resumen."""
    ruta = ruta or config.REVISION
    resumen = {"modificadas": 0, "confirmadas": 0, "ignoradas": []}
    if not ruta.exists():
        raise RuntimeError(f"No existe {ruta}: genérala primero con `python -m facturas hoja`")
    with ruta.open(newline="", encoding="utf-8-sig") as fh:
        filas = list(csv.DictReader(fh, delimiter=DELIM))
    for f in filas:
        try:
            actual = almacen.obtener(int(f["id"]))
        except (KeyError, TypeError, ValueError):
            actual = None
        if actual is None:
            resumen["ignoradas"].append(f"fila sin id válido: {f.get('id')!r}")
            continue
        cambios = {c: (f.get(c) or "").strip() for c in EDITABLES if (f.get(c) or "").strip() != (actual[c] or "").strip()}
        if "estado" in cambios:
            cambios["estado"] = cambios["estado"].lower()
            if cambios["estado"] not in ESTADOS:
                resumen["ignoradas"].append(f"#{actual['id']}: estado no válido {cambios.pop('estado')!r}")
        confirma = cambios.get("estado") == CONFIRMADA
        if confirma:
            cambios.pop("estado")
        if cambios:
            almacen.actualizar(actual["id"], **cambios)
            resumen["modificadas"] += 1
        if confirma:
            almacen.confirmar(actual["id"])  # lee la cuenta ya guardada y la aprende
            resumen["confirmadas"] += 1
    return resumen


def exportar(almacen: Almacen, incluir_listas: bool = False, destino: Path | None = None) -> int:
    """Escribe el CSV de importación con las confirmadas (y las `lista` si se pide). Devuelve cuántas."""
    destino = destino or config.IMPORTACION
    estados = (CONFIRMADA, LISTA) if incluir_listas else (CONFIRMADA,)
    filas = almacen.listar(estados)
    _escribir(
        destino,
        [cab for _, cab in COLUMNAS_IMPORTACION],
        ([(f[c] or "").replace(".", ",") if c in NUMERICAS else (f[c] or "") for c, _ in COLUMNAS_IMPORTACION] for f in filas),
    )
    return len(filas)
