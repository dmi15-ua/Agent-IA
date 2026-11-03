"""Pasos 4 y 5: hoja de revisión (CSV), detección de duplicados y exportación.

`revision.csv` hace de "hoja de cálculo": el gestor la abre en Excel / Google Sheets,
filtra por estado "revisar", corrige y cambia el estado a "confirmada".
Es CSV (delimitador `;`, UTF-8 con BOM) para que Excel en español lo abra bien.
"""
import csv
from pathlib import Path

from . import config
from .modelos import COLUMNAS_REVISION, CONFIRMADA, LISTA, REPETIDA

DELIM = ";"

# Columnas del CSV de importación. Cambiad esto al formato que pida el programa
# de contabilidad (A3, Contasol, Holded, Sage...). Importes con coma decimal.
COLUMNAS_IMPORTACION = (
    ("fecha", "Fecha"),
    ("numero_factura", "NumFactura"),
    ("nif_proveedor", "NIF"),
    ("proveedor", "Proveedor"),
    ("base_imponible", "Base"),
    ("tipo_iva", "TipoIVA"),
    ("cuota_iva", "CuotaIVA"),
    ("total", "Total"),
)


def leer(ruta: Path | None = None) -> list[dict]:
    ruta = ruta or config.REVISION
    if not ruta.exists():
        return []
    with ruta.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh, delimiter=DELIM))


def _escribir(filas: list[dict], ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNAS_REVISION, delimiter=DELIM, extrasaction="ignore")
        w.writeheader()
        w.writerows(filas)
    tmp.replace(ruta)  # escritura atómica: nunca queda la hoja a medias


def anadir(fila: dict, ruta: Path | None = None) -> dict:
    """Añade la fila marcando como `repetida` si su clave ya está en la hoja."""
    ruta = ruta or config.REVISION
    filas = leer(ruta)
    clave = fila.get("clave", "")
    if clave and any(f["clave"] == clave for f in filas):
        fila = {
            **fila,
            "estado": REPETIDA,
            "motivos": ("Factura ya registrada | " + fila.get("motivos", "")).strip(" |"),
        }
    filas.append(fila)
    _escribir(filas, ruta)
    return fila


def exportar(incluir_listas: bool = False, ruta_hoja: Path | None = None, destino: Path | None = None) -> int:
    """Escribe el CSV de importación con las filas confirmadas. Devuelve cuántas."""
    destino = destino or config.IMPORTACION
    validas = {CONFIRMADA} | ({LISTA} if incluir_listas else set())
    filas = [f for f in leer(ruta_hoja) if f["estado"].strip().lower() in validas]
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=DELIM)
        w.writerow([cab for _, cab in COLUMNAS_IMPORTACION])
        for f in filas:
            w.writerow(
                [
                    (f.get(campo) or "").replace(".", ",") if campo in ("base_imponible", "cuota_iva", "total") else f.get(campo, "")
                    for campo, _ in COLUMNAS_IMPORTACION
                ]
            )
    return len(filas)
