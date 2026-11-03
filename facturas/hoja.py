"""Hoja de revisión (CSV), detección de duplicados y exportación.

`revision.csv` hace de "hoja de cálculo": el gestor la abre en Excel / Google Sheets, filtra
por estado "revisar", mira la columna `a_revisar` (qué campos y por qué), corrige y cambia el
estado a "confirmada". Es CSV (delimitador `;`, UTF-8 con BOM) para que Excel en español lo abra.

Estados: lista · revisar · error (no se pudo leer: ver `error` y `que_hacer`) ·
repetida (misma clave que otra ya registrada) · confirmada (la pone el gestor a mano).
"""
import csv
from pathlib import Path

from . import config
from .extraccion.modelos import CAMPOS_NUMERO, CAMPOS_TEXTO, ERROR, Lectura

LISTA, REVISAR, REPETIDA, CONFIRMADA = "lista", "revisar", "repetida", "confirmada"
DELIM = ";"

COLUMNAS = (
    "recibida", "remitente", "archivo", "estado", "a_revisar", "error", "que_hacer",
    *CAMPOS_TEXTO, *CAMPOS_NUMERO, "clave",
)

# Columnas del CSV de importación. Adaptadlas al formato que pida el programa de
# contabilidad (A3, Contasol, Holded, Sage...). Importes con coma decimal.
COLUMNAS_IMPORTACION = (
    ("fecha_expedicion", "Fecha"),
    ("numero_factura", "NumFactura"),
    ("nif_proveedor", "NIF"),
    ("proveedor", "Proveedor"),
    ("base_imponible", "Base"),
    ("cuota_iva", "CuotaIVA"),
    ("retencion_irpf", "RetencionIRPF"),
    ("total", "Total"),
)
NUMERICAS = set(CAMPOS_NUMERO)


def _texto(v: object) -> str:
    if v is None:
        return ""
    return f"{v:.2f}" if isinstance(v, float) else str(v)


def clave_de(lectura: Lectura) -> str:
    """NIF|número|total en céntimos. Vacía si falta algo: sin eso no hay duplicado fiable."""
    c = lectura.campos
    if lectura.estado == ERROR or not all(c[n].valor not in (None, "") for n in ("nif_proveedor", "numero_factura", "total")):
        return ""
    nif = str(c["nif_proveedor"].valor).replace(" ", "").replace("-", "").upper()
    return f"{nif}|{str(c['numero_factura'].valor).strip().upper()}|{round(c['total'].valor * 100)}"


def fila_desde(lectura: Lectura, remitente: str, ruta: Path, recibida: str) -> dict:
    a_revisar = " | ".join(
        f"{n}: {lectura.campos[n].motivo or lectura.campos[n].estado}" for n in lectura.campos_a_revisar()
    )
    fila = {
        "recibida": recibida, "remitente": remitente, "archivo": str(ruta), "estado": lectura.estado,
        "a_revisar": a_revisar, "error": lectura.error, "que_hacer": lectura.que_hacer,
        "clave": clave_de(lectura),
    }
    for n in (*CAMPOS_TEXTO, *CAMPOS_NUMERO):
        c = lectura.campos.get(n)
        fila[n] = _texto(c.valor) if c else ""
    return fila


def leer(ruta: Path | None = None) -> list[dict]:
    ruta = ruta or config.REVISION
    if not ruta.exists():
        return []
    with ruta.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh, delimiter=DELIM))


def escribir(filas: list[dict], ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNAS, delimiter=DELIM, extrasaction="ignore")
        w.writeheader()
        w.writerows(filas)
    tmp.replace(ruta)  # escritura atómica: nunca queda la hoja a medias


def anadir(fila: dict, ruta: Path | None = None) -> dict:
    """Añade la fila marcando como `repetida` si su clave ya está en la hoja."""
    ruta = ruta or config.REVISION
    filas = leer(ruta)
    clave = fila.get("clave", "")
    if clave and any(f["clave"] == clave for f in filas):
        fila = {**fila, "estado": REPETIDA, "a_revisar": ("Factura ya registrada | " + fila["a_revisar"]).strip(" |")}
    filas.append(fila)
    escribir(filas, ruta)
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
            w.writerow([
                (f.get(campo) or "").replace(".", ",") if campo in NUMERICAS else f.get(campo, "")
                for campo, _ in COLUMNAS_IMPORTACION
            ])
    return len(filas)
