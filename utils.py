"""Utilidades compartidas.

Aquí viven las funciones puras que usan varios módulos, para no duplicarlas
ni crear dependencias raras entre ellos (por ejemplo, que database.py tenga
que importar de whatsapp_service.py solo por un `strip`).
"""
from typing import Optional


def normalizar_telefono(telefono: Optional[str]) -> str:
    """Lleva cualquier forma de escribir un teléfono a una sola.

    La centralita notifica la llamada perdida como "600112233", Evolution API
    manda el JID como "34600112233" (sin el "+") y los ejemplos de la API
    ponen "+34600112233". Sin normalizar, cada una de esas formas crea un
    paciente DISTINTO en la tabla: el mismo doctor ve al mismo paciente
    repetido y, peor, la conversación nueva empieza sin historial, así que
    la IA saluda como si fuera la primera vez que escribe.

    La forma canónica es internacional con "+" (+34600112233). Es la que
    devuelve Evolution API, de modo que el teléfono guardado y el que luego
    se busca coinciden siempre.
    """
    if not telefono:
        return ""

    crudo = str(telefono).strip()
    digitos = "".join(c for c in crudo if c.isdigit())

    # "abc" o un número sin dígitos: no hay nada que normalizar. Se devuelve
    # tal cual para que la validación de la base de datos sea la que avise.
    if not digitos:
        return crudo

    # Prefijo internacional con 00 en vez de +: 0034600112233
    if crudo.startswith("00") and len(digitos) > 2:
        return "+" + digitos[2:]

    if crudo.startswith("+"):
        return "+" + digitos

    # Móvil español de 9 digits sin prefijo ni "+": 600112233 -> +34600112233
    if len(digitos) == 9 and digitos[0] in "6789":
        return "+34" + digitos

    # Ya trae código de país en algún formato: 34600112233, 440207123456...
    if len(digitos) > 9:
        return "+" + digitos

    return digitos