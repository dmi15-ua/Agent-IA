"""Paso 3: validaciones por código, con reglas fijas. Lo que NO debe decidir la IA.

Importes siempre en céntimos (enteros) para no arrastrar errores de coma flotante.
"""
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from . import config
from .modelos import LISTA, REVISAR

# Formato del NIF/CIF/NIE. No comprueba la letra de control ni que exista.
NIF_RE = re.compile(
    r"^[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]$"  # CIF (empresas)
    r"|^\d{8}[A-Z]$"                        # DNI
    r"|^[XYZ]\d{7}[A-Z]$"                   # NIE
)

CAMPOS_OBLIGATORIOS = ("proveedor", "nif_proveedor", "numero_factura", "fecha", "total")


def a_centimos(valor) -> int | None:
    """'1.234,56' | '1234.56' | 1234.56 | None -> 123456 | None. Nunca lanza."""
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        d = Decimal(str(valor))
    else:
        t = re.sub(r"[^\d,.\-]", "", str(valor))  # quita € y espacios
        if not t:
            return None
        if "," in t and "." in t:
            # el último separador es el decimal
            if t.rfind(",") > t.rfind("."):
                t = t.replace(".", "").replace(",", ".")
            else:
                t = t.replace(",", "")
        elif "," in t:
            t = t.replace(",", ".")
        try:
            d = Decimal(t)
        except InvalidOperation:
            return None
    return int((d * 100).to_integral_value())


def normalizar_nif(nif) -> str:
    return re.sub(r"[\s.\-/]", "", str(nif or "")).upper()


def _fecha_ok(texto) -> tuple[bool, bool]:
    """(es_valida, es_futura)."""
    try:
        f = date.fromisoformat(str(texto or ""))
    except ValueError:
        return False, False
    return True, f > date.today()


def _vacio(v) -> bool:
    return v is None or str(v).strip() == ""


def validar(f: dict) -> dict:
    """Devuelve la factura normalizada + `clave`, `estado` (lista|revisar) y `motivos`."""
    base = a_centimos(f.get("base_imponible"))
    cuota = a_centimos(f.get("cuota_iva"))
    total = a_centimos(f.get("total"))
    try:
        tipo = Decimal(str(f.get("tipo_iva"))) if not _vacio(f.get("tipo_iva")) else None
    except InvalidOperation:
        tipo = None
    nif = normalizar_nif(f.get("nif_proveedor"))

    motivos: list[str] = []

    vacios = [k for k in CAMPOS_OBLIGATORIOS if _vacio(f.get(k))]
    if vacios:
        motivos.append("Faltan campos: " + ", ".join(vacios))

    if nif and not NIF_RE.match(nif):
        motivos.append("NIF con formato dudoso")

    if None in (base, cuota, total):
        if total is not None:
            motivos.append("No se pudo leer base o cuota de IVA")
    elif base + cuota != total:
        motivos.append("Base + IVA no suma el total")

    if tipo is not None and tipo not in config.TIPOS_IVA_VALIDOS:
        motivos.append(f"Tipo de IVA inusual: {tipo}%")
    elif tipo is not None and base is not None and cuota is not None:
        esperada = int((Decimal(base) * tipo / 100).to_integral_value())
        if abs(esperada - cuota) > config.TOLERANCIA_CUOTA_CENT:
            motivos.append("La cuota no corresponde a base × tipo de IVA")

    if total is not None and total <= 0:
        motivos.append("Total cero o negativo (¿rectificativa?)")

    if not _vacio(f.get("fecha")):
        valida, futura = _fecha_ok(f.get("fecha"))
        if not valida:
            motivos.append("Fecha no válida (se espera AAAA-MM-DD)")
        elif futura:
            motivos.append("Fecha en el futuro")

    if str(f.get("confianza") or "").lower() != "alta":
        motivos.append(f"Confianza del modelo: {f.get('confianza') or 'sin dato'}")
    if not _vacio(f.get("notas")):
        motivos.append("Notas del modelo: " + str(f["notas"]).strip())

    def euros(c):
        return "" if c is None else f"{c / 100:.2f}"

    clave = f"{nif}|{str(f.get('numero_factura') or '').strip().upper()}|{total}" if total is not None else ""
    # Sin NIF, número o total no hay forma fiable de detectar duplicados.
    if not (nif and not _vacio(f.get("numero_factura")) and total is not None):
        clave = ""

    return {
        **f,
        "nif_proveedor": nif,
        "base_imponible": euros(base),
        "cuota_iva": euros(cuota),
        "total": euros(total),
        "tipo_iva": "" if tipo is None else str(tipo.normalize()),
        "clave": clave,
        "estado": REVISAR if motivos else LISTA,
        "motivos": " | ".join(motivos),
    }
