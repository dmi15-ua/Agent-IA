"""Base de datos (SQLite): todas las facturas con sus campos y estado, y la cuenta contable de cada proveedor.

Es la fuente de verdad. `revision.csv` es solo una vista para que el gestor trabaje en Excel
(ver hoja.py). Detecta repetidas de dos formas:
  - por hash del archivo: el MISMO PDF otra vez. Ni se vuelve a leer (no gasta API ni tiempo).
  - por clave proveedor|número|total: la misma factura en otro archivo (reenviada, otro PDF).

Aprendizaje de cuenta contable: la primera vez que se ve un proveedor la elige una persona.
Las siguientes se propone esa cuenta, pero la factura va a revisión (cuenta "dudosa") hasta que se
haya confirmado CONFIRMACIONES_CUENTA veces seguidas con la misma cuenta. Si el gestor pone otra, se
aprende la nueva y se empieza a contar de nuevo.
"""
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from . import config
from .extraccion.modelos import CAMPOS_NUMERO, CAMPOS_TEXTO, ERROR, Lectura
from .extraccion.nif import normalizar as normalizar_nif, validar as validar_nif

LISTA, REVISAR, REPETIDA, CONFIRMADA = "lista", "revisar", "repetida", "confirmada"
CAMPOS = (*CAMPOS_TEXTO, *CAMPOS_NUMERO)
COLUMNAS = (
    "recibida", "remitente", "archivo", "hash", "estado", "a_revisar", "error", "que_hacer",
    *CAMPOS, "cuenta_contable", "cuenta_estado", "clave", "original_id", "detalle",
)
# Lo que el gestor puede corregir a mano desde la hoja.
EDITABLES = ("estado", *CAMPOS, "cuenta_contable")


def hash_de(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def _texto(v: object) -> str:
    if v is None:
        return ""
    return f"{v:.2f}" if isinstance(v, float) else str(v)


def clave_de(lectura: Lectura) -> str:
    """NIF|número|total en céntimos. Vacía si falta algo: sin eso no hay duplicado fiable."""
    c = lectura.campos
    if lectura.estado == ERROR or any(c[n].valor in (None, "") for n in ("nif_proveedor", "numero_factura", "total")):
        return ""
    return f"{normalizar_nif(c['nif_proveedor'].valor)}|{str(c['numero_factura'].valor).strip().upper()}|{round(c['total'].valor * 100)}"


def fila_desde(lectura: Lectura, remitente: str, ruta: Path, hash_: str) -> dict:
    a_revisar = " | ".join(f"{n}: {lectura.campos[n].motivo or lectura.campos[n].estado}" for n in lectura.campos_a_revisar())
    fila = {
        "recibida": datetime.now().isoformat(timespec="seconds"), "remitente": remitente, "archivo": str(ruta),
        "hash": hash_, "estado": lectura.estado, "a_revisar": a_revisar, "error": lectura.error,
        "que_hacer": lectura.que_hacer, "clave": clave_de(lectura), "cuenta_contable": "", "cuenta_estado": "",
        "original_id": None, "detalle": json.dumps(lectura.a_dict(), ensure_ascii=False),
    }
    for n in CAMPOS:
        c = lectura.campos.get(n)
        fila[n] = _texto(c.valor) if c else ""
    return fila


class Almacen:
    def __init__(self, ruta: Path | None = None) -> None:
        ruta = ruta or config.BASE_DATOS
        if str(ruta) != ":memory:":
            ruta.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(ruta))
        self.db.row_factory = sqlite3.Row
        cols = ", ".join(f"{c} {'INTEGER' if c == 'original_id' else 'TEXT'}" for c in COLUMNAS)
        self.db.executescript(f"""
            CREATE TABLE IF NOT EXISTS facturas (id INTEGER PRIMARY KEY AUTOINCREMENT, {cols});
            CREATE INDEX IF NOT EXISTS idx_hash ON facturas(hash);
            CREATE INDEX IF NOT EXISTS idx_clave ON facturas(clave);
            CREATE TABLE IF NOT EXISTS cuentas (
                nif TEXT PRIMARY KEY, proveedor TEXT, cuenta TEXT NOT NULL,
                confirmaciones INTEGER NOT NULL, actualizada TEXT);
        """)

    def cerrar(self) -> None:
        self.db.close()

    # ------------------------------------------------------------------ facturas

    def obtener(self, id_: int) -> dict | None:
        r = self.db.execute("SELECT * FROM facturas WHERE id = ?", (id_,)).fetchone()
        return dict(r) if r else None

    def listar(self, estados: tuple[str, ...] | None = None) -> list[dict]:
        sql, args = "SELECT * FROM facturas", ()
        if estados:
            sql += f" WHERE lower(estado) IN ({','.join('?' * len(estados))})"
            args = tuple(estados)
        return [dict(r) for r in self.db.execute(sql + " ORDER BY id", args)]

    def por_hash(self, hash_: str) -> dict | None:
        """La primera lectura válida de ese mismo archivo. Un `error` no cuenta: se reintenta."""
        r = self.db.execute(
            "SELECT * FROM facturas WHERE hash = ? AND estado NOT IN ('error', 'repetida') ORDER BY id LIMIT 1", (hash_,)
        ).fetchone()
        return dict(r) if r else None

    def _original_por_clave(self, clave: str) -> dict | None:
        r = self.db.execute(
            "SELECT * FROM facturas WHERE clave = ? AND estado != 'repetida' ORDER BY id LIMIT 1", (clave,)
        ).fetchone()
        return dict(r) if r else None

    def guardar(self, fila: dict) -> dict:
        """Guarda la fila (marcándola `repetida` si su clave ya existe) y devuelve la fila con su id."""
        fila = {c: fila.get(c, "" if c != "original_id" else None) for c in COLUMNAS}
        if fila["clave"] and (orig := self._original_por_clave(fila["clave"])):
            fila["estado"] = REPETIDA
            fila["original_id"] = orig["id"]
            fila["a_revisar"] = f"Factura ya registrada (#{orig['id']}) | {fila['a_revisar']}".strip(" |")
        cur = self.db.execute(
            f"INSERT INTO facturas ({','.join(COLUMNAS)}) VALUES ({','.join('?' * len(COLUMNAS))})",
            [fila[c] for c in COLUMNAS],
        )
        self.db.commit()
        fila["id"] = cur.lastrowid
        return fila

    def actualizar(self, id_: int, **campos: object) -> None:
        malos = set(campos) - set(COLUMNAS)
        if malos:
            raise ValueError(f"Columnas desconocidas: {malos}")
        self.db.execute(
            f"UPDATE facturas SET {', '.join(f'{c} = ?' for c in campos)} WHERE id = ?", [*campos.values(), id_]
        )
        self.db.commit()

    # ------------------------------------------------------------------ cuentas contables

    def cuenta_de(self, nif: str) -> dict | None:
        r = self.db.execute("SELECT * FROM cuentas WHERE nif = ?", (normalizar_nif(nif),)).fetchone()
        return dict(r) if r else None

    def proponer_cuenta(self, nif: str) -> tuple[str, str, str]:
        """(cuenta, estado, motivo). estado: '' sin proveedor · nueva · dudosa · ok."""
        if not normalizar_nif(nif):
            return "", "", ""
        c = self.cuenta_de(nif)
        if not c:
            return "", "nueva", "Proveedor nuevo: hay que elegir la cuenta contable"
        n = config.CONFIRMACIONES_CUENTA
        if c["confirmaciones"] < n:
            return c["cuenta"], "dudosa", f"Cuenta {c['cuenta']} sugerida, confirmada {c['confirmaciones']} de {n} veces"
        return c["cuenta"], "ok", ""

    def aprender_cuenta(self, nif: str, proveedor: str, cuenta: str) -> int:
        """Registra una confirmación humana. Misma cuenta: +1. Otra cuenta: se cambia y se cuenta desde 1."""
        nif, cuenta = normalizar_nif(nif), str(cuenta).strip()
        if not nif or not cuenta or not validar_nif(nif)[0]:
            return 0  # con un NIF mal leído se crearía un "proveedor" fantasma
        actual = self.cuenta_de(nif)
        n = actual["confirmaciones"] + 1 if actual and actual["cuenta"] == cuenta else 1
        self.db.execute(
            "INSERT INTO cuentas (nif, proveedor, cuenta, confirmaciones, actualizada) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(nif) DO UPDATE SET proveedor=excluded.proveedor, cuenta=excluded.cuenta, "
            "confirmaciones=excluded.confirmaciones, actualizada=excluded.actualizada",
            (nif, proveedor, cuenta, n, datetime.now().isoformat(timespec="seconds")),
        )
        self.db.commit()
        return n

    def confirmar(self, id_: int, cuenta: str | None = None) -> dict:
        """El gestor da la factura por buena. Si lleva cuenta, el sistema la aprende."""
        f = self.obtener(id_)
        if f is None:
            raise ValueError(f"No existe la factura #{id_}")
        if cuenta is not None:
            f["cuenta_contable"] = cuenta
        ya = f["estado"].strip().lower() == CONFIRMADA
        self.actualizar(id_, estado=CONFIRMADA, cuenta_contable=f["cuenta_contable"])
        if not ya:  # confirmar dos veces la misma factura no cuenta como dos confirmaciones
            self.aprender_cuenta(f["nif_proveedor"], f["proveedor"], f["cuenta_contable"])
        return self.obtener(id_)
