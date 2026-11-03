"""El único sitio que habla con un modelo de IA. Cambiar de proveedor = escribir otra clase aquí.

Un proveedor tiene un método: leer(ruta, instruccion) -> texto con la respuesta del modelo.
El resto del programa no sabe qué modelo hay detrás.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Optional, Protocol

EXTENSIONES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
MODELO_POR_DEFECTO = "claude-sonnet-5-5"  # se cambia con la variable FACTURAS_MODELO o --modelo
MODELO_GEMINI_POR_DEFECTO = "gemini-3.5-flash-lite"  # FACTURAS_MODELO_GEMINI


class Proveedor(Protocol):
    def leer(self, ruta: Path, instruccion: str) -> str: ...


class ProveedorClaude:
    """Lee la factura con la API de Anthropic (acepta PDF e imágenes).

    Necesita la variable de entorno ANTHROPIC_API_KEY y `pip install anthropic`.
    Antes de usarlo con facturas reales: revisad las condiciones de tratamiento y retención
    de datos del proveedor y tened firmado el contrato con la gestoría.
    """

    def __init__(self, modelo: Optional[str] = None, cliente: Any = None) -> None:
        self.modelo = modelo or os.environ.get("FACTURAS_MODELO") or MODELO_POR_DEFECTO
        if cliente is None:
            import anthropic  # import tardío: las pruebas y el modo simulado no lo necesitan

            cliente = anthropic.Anthropic()
        self._cliente = cliente

    def leer(self, ruta: Path, instruccion: str) -> str:
        tipo = EXTENSIONES[ruta.suffix.lower()]
        datos = base64.standard_b64encode(ruta.read_bytes()).decode("ascii")
        bloque_tipo = "document" if tipo == "application/pdf" else "image"
        respuesta = self._cliente.messages.create(
            model=self.modelo,
            max_tokens=2000,
            system=instruccion,
            messages=[{
                "role": "user",
                "content": [
                    {"type": bloque_tipo, "source": {"type": "base64", "media_type": tipo, "data": datos}},
                    {"type": "text", "text": "Lee esta factura y devuelve solo el JSON."},
                ],
            }],
        )
        return "".join(b.text for b in respuesta.content if getattr(b, "type", "") == "text")


class ProveedorSimulado:
    """Sin red ni clave: lee la respuesta de un archivo '<factura>.respuesta.json' junto a la factura.

    Sirve para probar el resto del programa y para las pruebas automáticas.
    """

    def leer(self, ruta: Path, instruccion: str) -> str:
        respuesta = ruta.with_name(ruta.name + ".respuesta.json")
        if not respuesta.exists():
            raise FileNotFoundError(f"No hay respuesta simulada: {respuesta.name}")
        return respuesta.read_text(encoding="utf-8")


class ProveedorGemini:
    """Lee la factura con la API de Google Gemini (PDF e imágenes). Solo necesita httpx y GEMINI_API_KEY."""

    def __init__(self, modelo: Optional[str] = None, clave: Optional[str] = None) -> None:
        self.modelo = modelo or os.environ.get("FACTURAS_MODELO_GEMINI") or MODELO_GEMINI_POR_DEFECTO
        self._clave = clave or os.environ.get("GEMINI_API_KEY", "")
        if not self._clave:
            raise RuntimeError("Falta la variable GEMINI_API_KEY")

    def leer(self, ruta: Path, instruccion: str) -> str:
        import httpx  # import tardío, como anthropic

        cuerpo = {
            "system_instruction": {"parts": [{"text": instruccion}]},
            "contents": [{"parts": [
                {"inline_data": {"mime_type": EXTENSIONES[ruta.suffix.lower()],
                                 "data": base64.standard_b64encode(ruta.read_bytes()).decode("ascii")}},
                {"text": "Lee esta factura y devuelve solo el JSON."},
            ]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
        }
        r = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.modelo}:generateContent",
            headers={"x-goog-api-key": self._clave}, json=cuerpo, timeout=120,
        )
        if r.status_code != 200:
            # No se vuelca el cuerpo: podría repetir contenido de la factura.
            raise RuntimeError(f"Gemini respondió HTTP {r.status_code}")
        try:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError("Gemini devolvió una respuesta sin texto") from e


class ProveedorVerificado:
    """Envuelve a un modelo de API y comprueba su respuesta contra el texto del PDF.

    Si el PDF tiene texto digital (casi todos los que llegan por correo), cada dato que el
    modelo da por "claro" se busca en ese texto; el que no aparece baja a "dudoso". Es la
    defensa contra datos inventados. Con fotos o PDF escaneados no se hace (haría falta OCR):
    la respuesta pasa tal cual.
    """

    def __init__(self, interno: Proveedor) -> None:
        self._interno = interno

    def leer(self, ruta: Path, instruccion: str) -> str:
        respuesta = self._interno.leer(ruta, instruccion)
        if ruta.suffix.lower() != ".pdf":
            return respuesta
        from .lector_local import LectorLocal
        from .lector_ollama import _comprobar_contra_el_texto

        try:
            texto = LectorLocal()._pdf_con_texto(ruta)
        except Exception:  # sin pdftotext o PDF raro: no se puede verificar, no es un error
            return respuesta
        if len(texto.strip()) < 40:  # PDF escaneado: no hay texto fiable
            return respuesta
        datos = _comprobar_contra_el_texto(respuesta, texto, None)
        return json.dumps(datos, ensure_ascii=False) if "campos" in datos else respuesta


LECTORES = ("local", "ollama", "gemini", "claude", "simulado")


def crear_proveedor(lector: str, modelo: Optional[str] = None) -> Proveedor:
    """local y ollama no envían nada fuera del equipo; gemini y claude sí (ver README)."""
    if lector == "simulado":
        return ProveedorSimulado()
    if lector == "local":
        from .lector_local import LectorLocal
        return LectorLocal()
    if lector == "ollama":
        from .lector_ollama import LectorOllama
        return LectorOllama(modelo=modelo)
    if lector == "gemini":
        return ProveedorVerificado(ProveedorGemini(modelo))
    if lector == "claude":
        return ProveedorVerificado(ProveedorClaude(modelo))
    raise ValueError(f"Lector desconocido: {lector!r} (opciones: {', '.join(LECTORES)})")
