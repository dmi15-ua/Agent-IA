"""Compara lo que ha leído el programa con los valores correctos y mide el acierto.

Uso:
    python -m facturas leer mis_facturas --salida resultados
    python -m facturas comparar mis_facturas/esperado.json resultados/resultado.json

El archivo esperado.json lo escribes tú, a mano, con los valores correctos:
    { "factura1.pdf": {"numero_factura": "F-12", "total": 121.0, ...}, ... }
Solo se comparan los campos que pongas. Mira ejemplos/esperado.json.

La cifra que más importa es "errores marcados como seguros": un campo mal leído que el programa
dio por bueno (estado ok). Esos son los que se cuelan sin que nadie los revise. Deben ser 0.
"""
from __future__ import annotations

import json
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path


def _texto(v: object) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", str(v)) if unicodedata.category(c) != "Mn")
    return " ".join(s.casefold().replace(".", "").replace(",", "").split())


def _igual(esperado: object, leido: object) -> bool:
    if isinstance(esperado, (int, float)) and not isinstance(esperado, bool):
        return isinstance(leido, (int, float)) and abs(float(esperado) - float(leido)) < 0.005
    return leido is not None and _texto(esperado) == _texto(leido)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print(__doc__)
        return 2
    esperado = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    leido = {l["archivo"]: l for l in json.loads(Path(argv[1]).read_text(encoding="utf-8"))}

    total = defaultdict(int)
    acierto = defaultdict(int)
    peligrosos: list[str] = []
    sin_resultado = 0

    for archivo, campos in esperado.items():
        l = leido.get(archivo)
        if l is None or l["estado"] == "error":
            sin_resultado += 1
            motivo = "no aparece en el resultado" if l is None else f"error: {l['error']}"
            print(f"  {archivo}: SIN LECTURA ({motivo})")
            continue
        fallos = []
        for nombre, correcto in campos.items():
            total[nombre] += 1
            campo = l["campos"][nombre]
            if _igual(correcto, campo["valor"]):
                acierto[nombre] += 1
            else:
                fallos.append(f"{nombre}: esperado {correcto!r}, leído {campo['valor']!r} [{campo['estado']}]")
                if campo["estado"] == "ok" and campo["valor"] is not None:
                    peligrosos.append(f"{archivo} · {nombre}: esperado {correcto!r}, leído {campo['valor']!r}")
        print(f"  {archivo}: {l['estado']:<8} " + ("todo correcto" if not fallos else ""))
        for f in fallos:
            print(f"      x {f}")

    print("\nAcierto por campo")
    for nombre in sorted(total):
        print(f"  {nombre:<18} {acierto[nombre]}/{total[nombre]}")
    t, a = sum(total.values()), sum(acierto.values())
    if t:
        print(f"  {'TOTAL':<18} {a}/{t}  ({100 * a / t:.0f} %)")
    if sin_resultado:
        print(f"\nFacturas sin lectura (error o ausentes): {sin_resultado}")
    print(f"\nERRORES MARCADOS COMO SEGUROS: {len(peligrosos)}   <- deben ser 0")
    for p in peligrosos:
        print(f"  ! {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
