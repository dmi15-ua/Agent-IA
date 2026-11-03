"""Paso 2: lectura de la factura con un modelo de visión.

El modelo solo LEE. No valida ni decide nada: eso lo hace validacion.py con reglas fijas.
"""
import base64
import json
import logging
import mimetypes
from pathlib import Path

import httpx

from . import config
from .modelos import CAMPOS_MODELO

logger = logging.getLogger(__name__)

PROMPT = """Eres un lector de facturas españolas. Te paso una factura (PDF o imagen).
Devuelve SOLO un objeto JSON, sin texto antes ni después y sin bloques de código, con
exactamente estos campos:

{
  "proveedor": "",
  "nif_proveedor": "",
  "numero_factura": "",
  "fecha": "AAAA-MM-DD",
  "base_imponible": 0.00,
  "tipo_iva": 21,
  "cuota_iva": 0.00,
  "total": 0.00,
  "confianza": "alta|media|baja",
  "notas": ""
}

Reglas:
- El proveedor es quien EMITE la factura, no a quien se le factura.
- NO inventes datos. Si un campo no se ve con claridad, déjalo vacío ("" o null).
  Un campo vacío lo corrige una persona; un dato inventado se cuela.
- Los importes son números con punto decimal (1234.56), sin símbolo de moneda ni
  separador de miles.
- La fecha es la de emisión de la factura, en formato AAAA-MM-DD.
- Si hay varios tipos de IVA, usa el del importe mayor y dilo en "notas".
- En "notas" explica todo lo ilegible, dudoso o raro (tachones, foto torcida, importes
  que no cuadran, factura rectificativa, ticket sin NIF...).
- "confianza": "alta" si leíste todo con claridad, "media" si dudas de algún campo,
  "baja" si el documento es difícil de leer o no parece una factura.
"""


class ErrorExtraccion(Exception):
    """El modelo no respondió o no devolvió un JSON utilizable."""


def _mime(ruta: Path) -> str:
    mime, _ = mimetypes.guess_type(ruta.name)
    if mime not in config.TIPOS_ADJUNTO:
        raise ErrorExtraccion(f"Tipo de archivo no soportado: {ruta.suffix or ruta.name}")
    return mime


def parsear_respuesta(texto: str) -> dict:
    """Saca el JSON de la respuesta aunque venga envuelto en ```json ... ```."""
    t = (texto or "").strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
    ini, fin = t.find("{"), t.rfind("}")
    if ini == -1 or fin <= ini:
        raise ErrorExtraccion(f"La respuesta no contiene JSON: {texto[:200]!r}")
    try:
        datos = json.loads(t[ini : fin + 1])
    except json.JSONDecodeError as e:
        raise ErrorExtraccion(f"JSON inválido del modelo: {e}") from e
    if not isinstance(datos, dict):
        raise ErrorExtraccion("El modelo no devolvió un objeto JSON")
    return {k: datos.get(k) for k in CAMPOS_MODELO}


def _post(url: str, headers: dict, cuerpo: dict) -> dict:
    try:
        r = httpx.post(url, headers=headers, json=cuerpo, timeout=config.TIMEOUT_API)
    except httpx.HTTPError as e:
        raise ErrorExtraccion(f"No se pudo contactar con el modelo: {e}") from e
    if r.status_code != 200:
        # No se vuelca el cuerpo entero: podría repetir contenido de la factura.
        raise ErrorExtraccion(f"El modelo respondió HTTP {r.status_code}: {r.text[:200]}")
    return r.json()


def extraer_gemini(ruta: Path) -> dict:
    if not config.GEMINI_API_KEY:
        raise ErrorExtraccion("Falta GEMINI_API_KEY")
    datos_b64 = base64.b64encode(ruta.read_bytes()).decode()
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{config.FACTURAS_GEMINI_MODEL}:generateContent"
    )
    cuerpo = {
        "contents": [
            {
                "parts": [
                    {"text": PROMPT},
                    {"inline_data": {"mime_type": _mime(ruta), "data": datos_b64}},
                ]
            }
        ],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
    }
    resp = _post(url, {"x-goog-api-key": config.GEMINI_API_KEY}, cuerpo)
    try:
        texto = resp["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as e:
        raise ErrorExtraccion(f"Respuesta de Gemini sin texto: {str(resp)[:200]}") from e
    return parsear_respuesta(texto)


def extraer_claude(ruta: Path) -> dict:
    if not config.ANTHROPIC_API_KEY:
        raise ErrorExtraccion("Falta ANTHROPIC_API_KEY")
    mime = _mime(ruta)
    bloque = {
        "type": "document" if mime == "application/pdf" else "image",
        "source": {
            "type": "base64",
            "media_type": mime,
            "data": base64.b64encode(ruta.read_bytes()).decode(),
        },
    }
    cuerpo = {
        "model": config.FACTURAS_CLAUDE_MODEL,
        "max_tokens": 1024,
        "temperature": 0,
        "messages": [{"role": "user", "content": [bloque, {"type": "text", "text": PROMPT}]}],
    }
    cabeceras = {"x-api-key": config.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"}
    resp = _post("https://api.anthropic.com/v1/messages", cabeceras, cuerpo)
    texto = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
    return parsear_respuesta(texto)


def extraer_simulado(ruta: Path) -> dict:
    """Lee `<factura>.json` junto al archivo. Sirve para probar el flujo sin API ni coste."""
    sidecar = ruta.with_name(ruta.name + ".json")
    if not sidecar.exists():
        sidecar = ruta.with_suffix(".json")
    if not sidecar.exists():
        raise ErrorExtraccion(f"Modo simulado: no existe {sidecar.name}")
    return parsear_respuesta(sidecar.read_text(encoding="utf-8"))


EXTRACTORES = {
    "gemini": extraer_gemini,
    "claude": extraer_claude,
    "simulado": extraer_simulado,
}


def extraer(ruta: Path, extractor: str | None = None) -> dict:
    nombre = extractor or config.EXTRACTOR
    try:
        fn = EXTRACTORES[nombre]
    except KeyError:
        raise ErrorExtraccion(f"Extractor desconocido: {nombre!r} ({', '.join(EXTRACTORES)})")
    return fn(ruta)
