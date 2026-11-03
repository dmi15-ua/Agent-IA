"""Lector con un modelo de IA que corre en vuestro propio ordenador (Ollama). Gratis, sin cuentas ni claves.

  1. Saca el texto de la factura (pdftotext, o OCR si es una foto / PDF escaneado).
  2. Se lo da al modelo con la misma instrucción que usaría cualquier otro lector.
  3. Comprueba que cada dato que el modelo da por "claro" APARECE de verdad en el texto de la factura.
     Los modelos pequeños a veces inventan: lo que no se encuentra en el texto baja a "dudoso".
  4. Después pasan las comprobaciones de siempre (NIF, fechas, base + IVA = total...).

Preparación (una vez):
    1. Instalar Ollama: https://ollama.com/download
    2. Descargar un modelo:   ollama pull qwen2.5:7b
    3. python3 leer_facturas.py mis_facturas --lector ollama

Cambiar de modelo: --modelo NOMBRE o la variable FACTURAS_MODELO_OLLAMA.
Si Ollama corre en otro equipo de la red: variable OLLAMA_HOST (por defecto http://localhost:11434).
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any, Optional

from .lector_local import LectorLocal
from .reglas_texto import CALIDAD_MINIMA

MODELO_OLLAMA_POR_DEFECTO = "qwen2.5:7b"
ESPERA_SEGUNDOS = 300  # en un portátil sin tarjeta gráfica un modelo de 7B tarda de 30 s a 2 min por factura
MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
         "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}


class OllamaNoDisponible(Exception):
    que_hacer = ("Comprueba que Ollama está instalado y en marcha (ollama serve) y que has descargado el modelo "
                 f"(ollama pull {MODELO_OLLAMA_POR_DEFECTO}).")


class LectorOllama:
    def __init__(self, modelo: Optional[str] = None, servidor: Optional[str] = None) -> None:
        self.modelo = modelo or os.environ.get("FACTURAS_MODELO_OLLAMA") or MODELO_OLLAMA_POR_DEFECTO
        self.servidor = (servidor or os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
        if not self.servidor.startswith("http"):
            self.servidor = "http://" + self.servidor
        self._texto_de = LectorLocal()

    def leer(self, ruta: Path, instruccion: str) -> str:
        texto, calidad = self._texto_de._texto(ruta)
        respuesta = self._preguntar(instruccion, texto)
        return json.dumps(_comprobar_contra_el_texto(respuesta, texto, calidad), ensure_ascii=False)

    def _preguntar(self, instruccion: str, texto: str) -> str:
        cuerpo = json.dumps({
            "model": self.modelo,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": instruccion},
                {"role": "user", "content": "Texto de la factura:\n\n" + texto + "\n\nDevuelve solo el JSON."},
            ],
        }).encode("utf-8")
        peticion = urllib.request.Request(self.servidor + "/api/chat", data=cuerpo,
                                          headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(peticion, timeout=ESPERA_SEGUNDOS) as r:
                return json.loads(r.read().decode("utf-8"))["message"]["content"]
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise OllamaNoDisponible(f"Ollama no tiene el modelo '{self.modelo}'.") from e
            raise OllamaNoDisponible(f"Ollama respondió con error {e.code}.") from e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise OllamaNoDisponible(f"No se pudo hablar con Ollama en {self.servidor} ({e}).") from e
        except (KeyError, json.JSONDecodeError) as e:
            raise OllamaNoDisponible("Ollama devolvió una respuesta que no se entiende.") from e


# ---------------------------------------------------------------- ¿el dato está de verdad en la factura?

def _alfanumerico(s: Any) -> str:
    return re.sub(r"[^0-9a-záéíóúüñ]", "", str(s).lower())


def _importes_del_texto(texto: str) -> list[float]:
    encontrados = []
    for t in re.findall(r"\d[\d.,]*\d|\d", texto):
        limpio = t
        m = re.search(r"[.,](\d{1,2})$", t)
        if m:
            entero = re.sub(r"[.,]", "", t[:m.start()])
            limpio = f"{entero}.{m.group(1)}"
        else:
            limpio = re.sub(r"[.,]", "", t)
        try:
            encontrados.append(float(limpio))
        except ValueError:
            pass
    return encontrados


def _fechas_del_texto(texto: str) -> set[str]:
    fechas: set[str] = set()

    def añadir(d: int, m: int, a: int) -> None:
        a = a + 2000 if a < 100 else a
        try:
            fechas.add(date(a, m, d).isoformat())
        except ValueError:
            pass

    for d, m, a in re.findall(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b", texto):
        añadir(int(d), int(m), int(a))
    for a, m, d in re.findall(r"\b(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})\b", texto):
        añadir(int(d), int(m), int(a))
    for d, mes, a in re.findall(r"\b(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de(?:l)?\s+(\d{4})\b", texto.lower()):
        if mes in MESES:
            añadir(int(d), MESES[mes], int(a))
    return fechas


def _aparece(nombre: str, valor: Any, texto: str, importes: list[float], fechas: set[str]) -> bool:
    if valor in (None, ""):
        return True
    if nombre in ("base_imponible", "cuota_iva", "total", "retencion_irpf"):
        try:
            return any(abs(abs(float(valor)) - i) < 0.005 for i in importes)
        except (TypeError, ValueError):
            return False
    if nombre == "fecha_expedicion":
        return str(valor) in fechas
    if nombre in ("numero_factura", "nif_proveedor", "nif_cliente", "proveedor", "cliente"):
        return _alfanumerico(valor) in _alfanumerico(texto)
    return True  # descripción y moneda no se comprueban


FORMAS_JURIDICAS = {"SL", "SLU", "SA", "SAU", "CB", "SC", "SCP", "SLL", "SCOOP", "COOP"}


def _forma_juridica_rota(nombre: Any) -> bool:
    """True si el nombre acaba en algo que parece una forma jurídica pero no lo es (ej. 'Cc.B.' por mala lectura del OCR).

    Los nombres de personas, sin forma jurídica, no se tocan.
    """
    palabras = str(nombre or "").split()
    if not palabras:
        return False
    ultima = palabras[-1]
    return "." in ultima and len(ultima) <= 7 and re.sub(r"[^A-Za-z]", "", ultima).upper() not in FORMAS_JURIDICAS


def _moneda(campo: dict[str, Any], texto: str) -> None:
    """La moneda se decide por reglas: los modelos pequeños a veces ponen aquí un importe."""
    valor = str(campo.get("valor") or "").strip()
    if re.fullmatch(r"[A-Za-z]{3}|€", valor) and valor.upper() not in ("€",):
        return
    if "€" in texto or re.search(r"\bEUR\b", texto, re.IGNORECASE):
        campo.update(valor="EUR", legible="claro", motivo="")
    elif valor:
        campo.update(legible="dudoso", motivo=f"Moneda no reconocida: {valor}")
    else:
        campo.update(valor=None, legible="claro", motivo="")


def _comprobar_contra_el_texto(respuesta: str, texto: str, calidad: Optional[float]) -> dict[str, Any]:
    """Baja a 'dudoso' lo que el modelo da por claro pero no se encuentra en la factura.

    Si la respuesta no es un JSON utilizable se deja tal cual: procesar.interpretar la rechaza con un error claro.
    """
    inicio, fin = respuesta.find("{"), respuesta.rfind("}")
    try:
        datos = json.loads(respuesta[inicio:fin + 1])
        campos = datos["campos"]
    except (ValueError, KeyError, TypeError):
        return {"respuesta_no_valida": respuesta[:200]}  # sin 'campos': interpretar() lo convierte en error
    if not isinstance(campos, dict):
        return {"respuesta_no_valida": respuesta[:200]}

    importes, fechas = _importes_del_texto(texto), _fechas_del_texto(texto)
    if isinstance(campos.get("moneda"), dict):
        _moneda(campos["moneda"], texto)
    for nombre, campo in campos.items():
        if not isinstance(campo, dict) or campo.get("legible") != "claro":
            continue
        if nombre in ("proveedor", "cliente") and _forma_juridica_rota(campo.get("valor")):
            campo["legible"] = "dudoso"
            campo["motivo"] = f"La forma jurídica no se reconoce ('{str(campo['valor']).split()[-1]}'): posible fallo de lectura"
            continue
        if not _aparece(nombre, campo.get("valor"), texto, importes, fechas):
            campo["legible"] = "dudoso"
            campo["motivo"] = "El modelo dio este valor, pero no aparece tal cual en el texto de la factura"
        elif calidad is not None and calidad < CALIDAD_MINIMA and campo.get("valor") not in (None, ""):
            campo["legible"] = "dudoso"
            campo["motivo"] = f"Texto leído con poca calidad ({calidad:.0f} %)"
    return datos
