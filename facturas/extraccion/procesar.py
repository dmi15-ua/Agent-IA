"""De la respuesta del modelo a una Lectura con estado por campo.

Reglas de oro:
  1. El modelo propone, el código comprueba. Una comprobación puede empeorar un campo
     (ok -> dudoso), nunca mejorarlo.
  2. Lo que no se lee se deja vacío. Nunca se rellena por deducción.
  3. Toda factura que entra termina en lista, revisar o error. Ninguna se pierde en silencio.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Optional

from . import nif
from .instruccion import INSTRUCCION
from .modelos import (
    CAMPOS_NUMERO, CAMPOS_TEXTO, DUDOSO, ERROR, LISTA, NO_LEIDO, OBLIGATORIOS, OK, REVISAR,
    TODOS_LOS_CAMPOS, Campo, Lectura,
)
from .proveedor import EXTENSIONES, Proveedor

TAMANO_MAXIMO_MB = 20  # margen de seguridad; los límites reales los marca el proveedor de IA
TOLERANCIA_CENTIMOS = 2  # redondeos habituales en facturas
# Tipos de IVA que damos por habituales. Revisadlos con un asesor (no cubre IGIC de Canarias).
TIPOS_IVA_HABITUALES = {0, 4, 5, 10, 21}


class ErrorLectura(Exception):
    """Algo impide procesar la factura. Lleva el motivo y lo que puede hacer la persona."""

    def __init__(self, motivo: str, que_hacer: str) -> None:
        super().__init__(motivo)
        self.motivo, self.que_hacer = motivo, que_hacer


# ---------------------------------------------------------------- interpretar la respuesta

def _extraer_json(texto: str) -> dict[str, Any]:
    inicio, fin = texto.find("{"), texto.rfind("}")
    if inicio == -1 or fin <= inicio:
        raise ErrorLectura("El modelo no devolvió un JSON.", "Reintenta. Si se repite, revisa la instrucción.")
    try:
        datos = json.loads(texto[inicio:fin + 1])
    except json.JSONDecodeError as e:
        raise ErrorLectura(f"La respuesta del modelo no es un JSON válido ({e.msg}).", "Reintenta la lectura.") from e
    if not isinstance(datos, dict):
        raise ErrorLectura("La respuesta del modelo no tiene la forma esperada.", "Reintenta la lectura.")
    return datos


def _a_numero(valor: Any) -> Optional[float]:
    if valor is None or valor == "":
        return None
    if isinstance(valor, bool):
        raise ValueError("booleano")
    return float(str(valor).replace(",", "."))


def interpretar(texto: str, archivo: str) -> Lectura:
    """Convierte la respuesta del modelo en una Lectura (sin las comprobaciones del código)."""
    datos = _extraer_json(texto)
    if datos.get("es_factura") is False:
        raise ErrorLectura(
            "El documento no parece una factura.",
            "Comprueba el archivo. Si no es una factura, descártalo; si lo es, pide al cliente una copia más clara.",
        )
    brutos = datos.get("campos")
    if not isinstance(brutos, dict):
        raise ErrorLectura("Falta la sección 'campos' en la respuesta del modelo.", "Reintenta la lectura.")

    lectura = Lectura(archivo=archivo)
    for nombre in TODOS_LOS_CAMPOS:
        lectura.campos[nombre] = _interpretar_campo(nombre, brutos.get(nombre))

    desglose = datos.get("desglose_iva")
    if isinstance(desglose, list):
        for linea in desglose:
            try:
                lectura.desglose_iva.append({k: _a_numero(linea.get(k)) for k in ("tipo", "base", "cuota")})
            except (ValueError, AttributeError):
                lectura.campos["cuota_iva"].avisar("El desglose de IVA no se pudo interpretar")
    return lectura


def _interpretar_campo(nombre: str, bruto: Any) -> Campo:
    if not isinstance(bruto, dict):
        return Campo(None, NO_LEIDO, "El modelo no devolvió este campo")
    legible, motivo = bruto.get("legible"), str(bruto.get("motivo") or "")
    valor = bruto.get("valor")
    try:
        valor = _a_numero(valor) if nombre in CAMPOS_NUMERO else (None if valor in (None, "") else str(valor).strip())
    except ValueError:
        return Campo(None, NO_LEIDO, f"Importe no interpretable: {bruto.get('valor')!r}")
    if legible == "ilegible":
        return Campo(None, NO_LEIDO, motivo or "No se puede leer")
    if legible == "dudoso":
        return Campo(valor, DUDOSO, motivo or "El lector no está seguro")
    if legible == "claro":
        return Campo(valor, OK, motivo)
    return Campo(valor, DUDOSO, "El modelo no indicó si lo leyó con claridad")


# ---------------------------------------------------------------- comprobaciones del código

def _centimos(x: Optional[float]) -> Optional[int]:
    return None if x is None else round(x * 100)


def validar(lectura: Lectura) -> Lectura:
    """Comprobaciones fijas. Solo pueden empeorar el estado de un campo, nunca mejorarlo."""
    c = lectura.campos

    for nombre in OBLIGATORIOS:
        if c[nombre].valor in (None, "") and c[nombre].estado == OK:
            c[nombre].estado, c[nombre].motivo = NO_LEIDO, "Falta en la factura o no se detectó"

    for nombre in ("nif_proveedor", "nif_cliente"):
        valor = c[nombre].valor
        if valor:
            valido, motivo = nif.validar(valor)  # formato Y dígito/letra de control
            if not valido:
                arreglado = nif.reparar(valor) if c[nombre].estado != NO_LEIDO else None
                if arreglado:
                    # Corrección por confusión típica del OCR (8↔B, 0↔O...). Nunca queda como `ok`.
                    c[nombre].valor = arreglado
                    c[nombre].avisar(f"NIF corregido de {valor} a {arreglado} (el leído no es válido, el corregido sí): confirmar")
                else:
                    c[nombre].avisar(f"NIF no válido ({motivo}): {valor}")

    fecha = c["fecha_expedicion"].valor
    if fecha:
        try:
            if date.fromisoformat(str(fecha)) > date.today():
                c["fecha_expedicion"].avisar("La fecha es posterior a hoy")
        except ValueError:
            c["fecha_expedicion"].avisar(f"Fecha no válida: {fecha}")

    moneda = c["moneda"].valor
    if moneda and str(moneda).upper() not in ("EUR", "€"):
        c["moneda"].avisar(f"Moneda distinta de EUR: {moneda}")

    # La retención de IRPF es un importe retenido: se guarda siempre en positivo, aunque la factura lo
    # imprima como "-30,00" (el modelo copia el signo). Es una convención, no una duda de lectura.
    ret = c["retencion_irpf"]
    if isinstance(ret.valor, (int, float)) and ret.valor < 0:
        ret.valor = abs(ret.valor)

    _comprobar_importes(lectura)
    return lectura


def _comprobar_importes(lectura: Lectura) -> None:
    c = lectura.campos
    base, cuota, total = (_centimos(c[n].valor) for n in ("base_imponible", "cuota_iva", "total"))
    retencion = _centimos(c["retencion_irpf"].valor) or 0

    if None not in (base, cuota, total):
        # Según la factura, el total puede incluir o no la retención de IRPF: se aceptan las dos.
        posibles = (base + cuota, base + cuota - abs(retencion))
        if all(abs(p - total) > TOLERANCIA_CENTIMOS for p in posibles):
            motivo = f"Base + IVA ({posibles[0] / 100:.2f}) no suma el total ({total / 100:.2f})"
            for nombre in ("base_imponible", "cuota_iva", "total"):
                c[nombre].avisar(motivo)

    if lectura.desglose_iva:
        lineas = [l for l in lectura.desglose_iva if None not in l.values()]
        for linea in lineas:
            if linea["tipo"] not in TIPOS_IVA_HABITUALES:
                c["cuota_iva"].avisar(f"Tipo de IVA poco habitual: {linea['tipo']:g} %")
            esperada = round(_centimos(linea["base"]) * linea["tipo"] / 100)
            if abs(esperada - _centimos(linea["cuota"])) > TOLERANCIA_CENTIMOS:
                c["cuota_iva"].avisar(
                    f"En la línea del {linea['tipo']:g} %, la cuota ({linea['cuota']:.2f}) no coincide con la base"
                )
        margen = TOLERANCIA_CENTIMOS * max(len(lineas), 1)
        if lineas and base is not None and abs(sum(_centimos(l["base"]) for l in lineas) - base) > margen:
            c["base_imponible"].avisar("La suma del desglose de IVA no coincide con la base imponible")
        if lineas and cuota is not None and abs(sum(_centimos(l["cuota"]) for l in lineas) - cuota) > margen:
            c["cuota_iva"].avisar("La suma del desglose de IVA no coincide con la cuota")


# ---------------------------------------------------------------- procesar archivos

def procesar_archivo(ruta: Path, proveedor: Proveedor) -> Lectura:
    """Procesa un archivo. Nunca lanza excepciones: o devuelve lista/revisar, o un error explicado."""
    nombre = ruta.name
    try:
        _comprobar_archivo(ruta)
        try:
            texto = proveedor.leer(ruta, INSTRUCCION)
        except Exception as e:  # OCR que no entiende la imagen, fallo de red o de clave, PDF dañado...
            raise ErrorLectura(
                f"No se pudo leer el archivo ({type(e).__name__}: {e}).",
                getattr(e, "que_hacer", "Reintenta. Si se repite, revisa el lector (conexión, clave o programas instalados)."),
            ) from e
        lectura = validar(interpretar(texto, nombre))
        lectura.estado = REVISAR if lectura.campos_a_revisar() else LISTA
        return lectura
    except ErrorLectura as e:
        return Lectura(archivo=nombre, estado=ERROR, error=e.motivo, que_hacer=e.que_hacer)


def _comprobar_archivo(ruta: Path) -> None:
    if not ruta.is_file():
        raise ErrorLectura("El archivo no existe.", "Comprueba la ruta.")
    if ruta.suffix.lower() not in EXTENSIONES:
        raise ErrorLectura(
            f"Formato no soportado ({ruta.suffix or 'sin extensión'}).",
            "Pide al cliente la factura en PDF, JPG, PNG o WEBP.",
        )
    tamano = ruta.stat().st_size
    if tamano == 0:
        raise ErrorLectura("El archivo está vacío.", "Pide al cliente que vuelva a enviarlo.")
    if tamano > TAMANO_MAXIMO_MB * 1024 * 1024:
        raise ErrorLectura(f"El archivo pesa más de {TAMANO_MAXIMO_MB} MB.", "Pide una versión más ligera.")


def archivos_de(carpeta: Path) -> list[Path]:
    """Las facturas de una carpeta, sin ocultos, sin respuestas simuladas ni esperado.json."""
    return sorted(
        p for p in carpeta.iterdir()
        if p.is_file() and not p.name.startswith(".") and not p.name.endswith(".respuesta.json")
        and p.name != "esperado.json"  # los valores correctos para comparar.py no son una factura
    )


def procesar_carpeta(carpeta: Path, proveedor: Proveedor) -> list[Lectura]:
    """Una Lectura por cada archivo de la carpeta. Si entran N, salen N."""
    return [procesar_archivo(p, proveedor) for p in archivos_de(carpeta)]
