"""Del texto de una factura a los campos, con reglas (sin IA).

Recibe el texto que sacó el OCR o el PDF y devuelve un diccionario con la MISMA forma que
devuelve el modelo (es_factura, campos con "legible", desglose_iva), así que el resto del
programa no distingue de dónde viene.

Es heurístico: acierta con facturas de formato habitual y duda cuando no está seguro.
Regla de oro: ante la duda, "dudoso" o "ilegible", nunca un valor inventado.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Any, Optional

CALIDAD_MINIMA = 60  # por debajo de este % de confianza del OCR, ningún campo se da por claro

MESES = {m: i for i, m in enumerate(
    "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split(), 1)}

IMPORTE = re.compile(r"(?<![\d.,/])-?\d{1,3}(?:\.\d{3})+,\d{2}(?![\d]|[.,]\d)|(?<![\d.,/])-?\d+,\d{2}(?!\d|[.,]\d)|(?<![\d.,/])-?\d+\.\d{2}(?!\d|[.,]\d)")
PORCENTAJE = re.compile(r"(\d{1,2}(?:[.,]\d{1,2})?)\s*%")
NIF = re.compile(r"\b([ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]|\d{8}[A-Z]|[XYZ]\d{7}[A-Z])\b")
NIF_ETIQUETADO = re.compile(r"\b(?:NIF|CIF|N\.I\.F\.?|C\.I\.F\.?)\s*[:.\-]?\s*([A-Z0-9][A-Z0-9\-\.]{7,11})", re.IGNORECASE)
FECHA_NUM = r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4}|\d{2})"
FECHA_TXT = r"(\d{1,2})\s+de\s+(" + "|".join(MESES) + r")\s+(?:de\s+)?(\d{4})"
SUFIJO_EMPRESA = re.compile(r"\b(?:S\.?\s?L\.?\s?U?\.?|S\.?\s?A\.?|S\.?\s?C\.?|C\.?\s?B\.?|S\.?\s?COOP\.?|S\.?L\.?L\.?)\s*$", re.IGNORECASE)
MARCADOR_CLIENTE = re.compile(r"facturar a|factura a|cliente|destinatario|comprador|bill to|datos del cliente")
PALABRAS_FACTURA = ("factura", "iva", "total", "nif", "cif", "base imponible", "invoice")


def _norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()


def _campo(valor: Any = None, legible: str = "claro", motivo: str = "") -> dict[str, Any]:
    return {"valor": valor, "legible": legible, "motivo": motivo}


def _ilegible(motivo: str) -> dict[str, Any]:
    return _campo(None, "ilegible", motivo)


def _a_float(texto: str) -> float:
    t = texto.replace(" ", "")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    return float(t)


def _importes(linea: str) -> list[float]:
    return [_a_float(m) for m in IMPORTE.findall(linea)]


def _elegir(candidatos: list[Any], etiqueta: str, *, mayor: bool = False) -> dict[str, Any]:
    """Un único valor posible = claro. Varios distintos = dudoso, con el elegido."""
    unicos = list(dict.fromkeys(candidatos))
    if not unicos:
        return _ilegible(f"No se encontró {etiqueta}")
    if len(unicos) == 1:
        return _campo(unicos[0])
    elegido = max(unicos, key=abs) if mayor else unicos[0]
    return _campo(elegido, "dudoso", f"Aparecen varios valores posibles: {', '.join(str(u) for u in unicos)}")


# ---------------------------------------------------------------- campos concretos

def _fechas(linea: str) -> list[str]:
    salida = []
    for d, m, a in re.findall(FECHA_NUM, linea):
        salida.append((int(a) + 2000 if len(a) == 2 else int(a), int(m), int(d)))
    for d, mes, a in re.findall(FECHA_TXT, _norm(linea)):
        salida.append((int(a), MESES[mes], int(d)))
    validas = []
    for a, m, d in salida:
        try:
            validas.append(date(a, m, d).isoformat())
        except ValueError:
            continue
    return validas


def _fecha(lineas: list[str]) -> dict[str, Any]:
    etiquetadas, sueltas = [], []
    for linea in lineas:
        n = _norm(linea)
        for m in re.finditer(r"fecha(?: de)?(?: expedicion| emision| factura)?\s*[:.]?\s*", n):
            etiquetadas += _fechas(linea[m.end():].split("  ")[0][:40])
        if "vencim" not in n and "venc." not in n:
            sueltas += _fechas(linea)
    return _elegir(etiquetadas or sueltas, "la fecha")


def _numero(lineas: list[str]) -> dict[str, Any]:
    patrones = [
        r"(?:factura|invoice)\s*(?:(?:n[º°o2]|num(?:ero)?|no|#)\.?)?\s*[:.\-]?\s*(?=[A-Z0-9\-/.]*\d)([A-Z0-9][A-Z0-9\-/.]{1,24})",
        # El OCR confunde "Nº" con N2, N*, No, N°...: se acepta hasta dos símbolos entre la N y los dos puntos.
        r"\bn[\W2o0º°]{0,2}\s*(?:de factura)?\s*:\s*([A-Z0-9][A-Z0-9\-/.]{0,24})",
        r"\bn[uú]mero(?: de factura)?\s*[:.]?\s*([A-Z0-9][A-Z0-9\-/.]{0,24})",
    ]
    candidatos = []
    for linea in lineas:
        if "total" in _norm(linea):  # "TOTAL FACTURA 1.493,82" no lleva el número de factura
            continue
        for p in patrones:
            for m in re.finditer(p, linea, re.IGNORECASE):
                valor = m.group(1).rstrip(".,-/")
                resto = linea[m.end(1):m.end(1) + 3]
                parece_importe = bool(re.match(r"^[.,]\d", resto)) or bool(IMPORTE.fullmatch(valor))
                if valor and any(ch.isdigit() for ch in valor) and not parece_importe:
                    candidatos.append(valor)
    return _elegir(candidatos, "el número de factura")


def _nombre(linea: Optional[str]) -> dict[str, Any]:
    if not linea:
        return _ilegible("No se encontró el nombre")
    limpio = re.split(r"\b(?:factura|invoice|nif|cif)\b", linea, flags=re.IGNORECASE)[0].strip(" -:|,")
    if not limpio:
        return _ilegible("No se encontró el nombre")
    if SUFIJO_EMPRESA.search(limpio):
        return _campo(limpio)
    return _campo(limpio, "dudoso", "Nombre deducido por su posición, sin forma jurídica que lo confirme")


def _proveedor_y_cliente(lineas: list[str]) -> tuple[dict, dict, dict, dict]:
    normas = [_norm(l) for l in lineas]
    marcador = next((i for i, n in enumerate(normas) if MARCADOR_CLIENTE.search(n)), None)

    # Nombre del proveedor: primera línea con texto útil.
    nombre_prov = next((l for l in lineas[:4] if re.split(r"\b(?:factura|invoice|nif|cif)\b", l, flags=re.I)[0].strip(" -:|,")), None)
    proveedor = _nombre(nombre_prov)

    # Nombre del cliente: texto tras el marcador, o la línea siguiente.
    cliente = _ilegible("No se encontró el cliente")
    if marcador is not None:
        resto = re.split(r"[:]", lineas[marcador], maxsplit=1)
        mismo = resto[1].strip() if len(resto) == 2 else ""
        siguiente = next((l for l in lineas[marcador + 1:marcador + 4] if not re.search(r"\b(nif|cif)\b", _norm(l))), None)
        cliente = _nombre(mismo or siguiente)

    # NIF: primero los etiquetados ("NIF: ..."), si no, cualquier NIF suelto.
    encontrados: list[tuple[int, str]] = []
    for i, l in enumerate(lineas):
        for m in NIF_ETIQUETADO.finditer(l):
            encontrados.append((i, re.sub(r"[\-.]", "", m.group(1).upper())))
        if not NIF_ETIQUETADO.search(l):
            encontrados += [(i, m.group(1)) for m in NIF.finditer(l.upper())]

    antes = [v for i, v in encontrados if marcador is None or i < marcador]
    despues = [v for i, v in encontrados if marcador is not None and i >= marcador]
    if marcador is None and len(antes) >= 2:
        nif_prov = _campo(antes[0], "dudoso", "Asignado por orden de aparición")
        nif_cli = _campo(antes[1], "dudoso", "Asignado por orden de aparición")
    else:
        nif_prov = _campo(antes[0]) if antes else _ilegible("No se encontró el NIF del proveedor")
        nif_cli = _campo(despues[0]) if despues else _ilegible("No se encontró el NIF del cliente")
        if marcador is None and nif_prov["legible"] == "claro":
            nif_prov = _campo(antes[0], "dudoso", "No se pudo separar proveedor y cliente")
    for nif in (nif_prov, nif_cli):
        if nif["valor"] and nif["legible"] == "claro" and not NIF.fullmatch(nif["valor"]):
            nif["legible"], nif["motivo"] = "dudoso", f"Formato de NIF dudoso: {nif['valor']}"
    return proveedor, nif_prov, cliente, nif_cli


def _importes_factura(lineas: list[str]) -> tuple[dict, dict, dict, dict, list[dict]]:
    base_c, total_c, ret_c, cuota_c = [], [], [], []
    desglose: list[dict[str, Any]] = []

    for linea in lineas:
        n, cifras = _norm(linea), _importes(linea)
        if not cifras:
            continue
        pct = PORCENTAJE.search(linea)
        tiene_iva = re.search(r"\bi\.?v\.?a\.?\b", n) is not None
        if re.search(r"irpf|retenc", n):
            ret_c.append(abs(cifras[-1]))
        elif (tiene_iva and pct) or (pct and len(cifras) >= 2 and float(pct.group(1).replace(",", ".")) in (0, 4, 5, 10, 21)):
            tipo = float(pct.group(1).replace(",", "."))
            desglose.append({"tipo": tipo, "base": cifras[0] if len(cifras) >= 2 else None, "cuota": cifras[-1]})
        elif re.search(r"total iva|cuota iva|importe iva", n) or (tiene_iva and "total" not in n):
            cuota_c.append(cifras[-1])
        elif re.search(r"base imponible|\bbase\b|\bneto\b|subtotal", n) and "total" not in n.replace("subtotal", ""):
            base_c.append(cifras[-1])
        elif "total" in n.replace("subtotal", "") and not re.search(r"descuento|base", n):
            total_c.append(cifras[-1])

    base = _elegir(base_c, "la base imponible", mayor=True)
    total = _elegir(total_c, "el total", mayor=True)
    retencion = _campo(_elegir(ret_c, "la retención")["valor"]) if ret_c else _campo(None)

    if len(desglose) == 1 and desglose[0]["base"] is None and base["valor"] is not None:
        desglose[0]["base"] = base["valor"]
    if desglose:
        cuota = _campo(round(sum(l["cuota"] for l in desglose), 2))
        if base["valor"] is None and all(l["base"] is not None for l in desglose):
            base = _campo(round(sum(l["base"] for l in desglose), 2))
    else:
        cuota = _elegir(cuota_c, "la cuota de IVA")
    return base, cuota, total, retencion, desglose


# ---------------------------------------------------------------- punto de entrada

def extraer(texto: str, calidad: Optional[float] = None) -> dict[str, Any]:
    """Devuelve el diccionario con la misma forma que el modelo. `calidad` es la confianza del OCR (0-100)."""
    lineas = [l.strip() for l in texto.splitlines() if l.strip()]
    normal = _norm(texto)
    hay_importes = any(_importes(l) for l in lineas)
    if sum(p in normal for p in PALABRAS_FACTURA) < 2 or not hay_importes:
        return {"es_factura": False}

    proveedor, nif_prov, cliente, nif_cli = _proveedor_y_cliente(lineas)
    base, cuota, total, retencion, desglose = _importes_factura(lineas)
    moneda = _campo("EUR") if ("€" in texto or re.search(r"\beur\b", normal)) else _campo(None)

    campos = {
        "numero_factura": _numero(lineas),
        "fecha_expedicion": _fecha(lineas),
        "proveedor": proveedor, "nif_proveedor": nif_prov,
        "cliente": cliente, "nif_cliente": nif_cli,
        "base_imponible": base, "cuota_iva": cuota, "total": total,
        "retencion_irpf": retencion,
        "descripcion": _campo(None),
        "moneda": moneda,
    }
    if calidad is not None and calidad < CALIDAD_MINIMA:
        for c in campos.values():
            if c["legible"] == "claro" and c["valor"] is not None:
                c["legible"], c["motivo"] = "dudoso", f"Calidad de lectura baja ({calidad:.0f} %)"
    return {"es_factura": True, "campos": campos, "desglose_iva": desglose}
