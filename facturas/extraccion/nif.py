"""Validación completa de NIF (DNI), NIE y CIF: formato Y dígito/letra de control.

Comprueba que el número es matemáticamente posible, no que esté dado de alta. Detecta casi
todos los fallos típicos del OCR (una O por un 0, un 8 por un B, un 1 por una I...).
"""
import re

_LETRAS_DNI = "TRWAGMYFPDXBNJZSQVHLCKE"
_CONTROL_CIF = "JABCDEFGHI"
_DNI = re.compile(r"^(\d{8})([A-Z])$")
_NIE = re.compile(r"^([XYZ])(\d{7})([A-Z])$")
_CIF = re.compile(r"^([ABCDEFGHJNPQRSUVW])(\d{7})([0-9A-J])$")
_ESPECIAL = re.compile(r"^([KLM])(\d{7})([0-9A-Z])$")  # españoles sin DNI / menores
# Entidades que obligatoriamente llevan LETRA de control; las A, B, E, H, la llevan en DÍGITO.
_SOLO_LETRA = set("NPQRSW")
_SOLO_DIGITO = set("ABEH")


def normalizar(nif: object) -> str:
    return re.sub(r"[\s.\-/]", "", str(nif or "")).upper()


def _control_cif(digitos: str) -> int:
    pares = sum(int(d) for d in digitos[1::2])
    impares = sum(sum(divmod(int(d) * 2, 10)) for d in digitos[0::2])
    return (10 - (pares + impares) % 10) % 10


def validar(nif: object) -> tuple[bool, str]:
    """(es_valido, motivo). El motivo está vacío si es válido."""
    n = normalizar(nif)
    if m := _DNI.match(n):
        ok = _LETRAS_DNI[int(m[1]) % 23] == m[2]
        return ok, "" if ok else "la letra de control no coincide con el número"
    if m := _NIE.match(n):
        num = int(str("XYZ".index(m[1])) + m[2])
        ok = _LETRAS_DNI[num % 23] == m[3]
        return ok, "" if ok else "la letra de control no coincide con el número"
    if m := _CIF.match(n):
        c = _control_cif(m[2])
        digito, letra = str(c), _CONTROL_CIF[c]
        if m[1] in _SOLO_LETRA:
            ok = m[3] == letra
        elif m[1] in _SOLO_DIGITO:
            ok = m[3] == digito
        else:
            ok = m[3] in (digito, letra)
        return ok, "" if ok else "el dígito de control no coincide con el número"
    if m := _ESPECIAL.match(n):
        c = _control_cif(m[2])
        ok = m[3] in (str(c), _CONTROL_CIF[c])
        return ok, "" if ok else "el dígito de control no coincide con el número"
    return False, "formato no reconocido"


# Parejas de caracteres que el OCR confunde entre sí.
_CONFUSIONES = [("8", "B"), ("0", "O"), ("0", "D"), ("0", "Q"), ("1", "I"), ("1", "L"), ("2", "Z"),
                ("5", "S"), ("6", "G"), ("4", "A"), ("7", "T")]
_ALTERNATIVAS: dict[str, str] = {}
for _a, _b in _CONFUSIONES:
    _ALTERNATIVAS[_a] = _ALTERNATIVAS.get(_a, "") + _b
    _ALTERNATIVAS[_b] = _ALTERNATIVAS.get(_b, "") + _a


def reparar(nif: object, max_cambios: int = 2) -> str | None:
    """Si el NIF leído NO es válido, busca la corrección por confusiones típicas del OCR (8↔B, 0↔O/D, 1↔I, 5↔S...).

    Devuelve el NIF corregido solo si hay UNA ÚNICA corrección con dígito de control válido; con varias
    posibles (o ninguna) devuelve None. Quien lo use debe presentarlo siempre como dudoso: el control
    hace improbable una corrección falsa, pero no imposible.
    """
    from itertools import combinations, product

    n = normalizar(nif)
    if len(n) != 9 or validar(n)[0]:
        return None
    candidatos: set[str] = set()
    for k in range(1, max_cambios + 1):
        for posiciones in combinations(range(9), k):
            opciones = [_ALTERNATIVAS.get(n[p], "") for p in posiciones]
            for cambios in product(*opciones):
                lista = list(n)
                for p, ch in zip(posiciones, cambios):
                    lista[p] = ch
                cand = "".join(lista)
                if validar(cand)[0]:
                    candidatos.add(cand)
        if candidatos:  # se prefiere siempre la corrección con menos cambios
            break
    return candidatos.pop() if len(candidatos) == 1 else None
