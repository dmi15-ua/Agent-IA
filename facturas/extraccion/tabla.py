"""Salida: una tabla legible (CSV) y el detalle completo (JSON).

CSV con ";" y coma decimal, en UTF-8 con BOM, para que Excel en español lo abra bien.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

from .modelos import CAMPOS_NUMERO, CAMPOS_TEXTO, ERROR, Lectura

COLUMNAS = ["archivo", "estado", "a_revisar", "error", "que_hacer", *CAMPOS_TEXTO, *CAMPOS_NUMERO]


def _valor(v: object) -> str:
    if v is None:
        return ""
    return f"{v:.2f}".replace(".", ",") if isinstance(v, float) else str(v)


def _fila(l: Lectura) -> list[str]:
    a_revisar = " | ".join(
        f"{n}: {l.campos[n].motivo or l.campos[n].estado}" for n in l.campos_a_revisar()
    )
    base = [l.archivo, l.estado, a_revisar, l.error, l.que_hacer]
    if l.estado == ERROR:
        return base + [""] * (len(CAMPOS_TEXTO) + len(CAMPOS_NUMERO))
    return base + [_valor(l.campos[n].valor) for n in (*CAMPOS_TEXTO, *CAMPOS_NUMERO)]


def escribir_csv(lecturas: Iterable[Lectura], ruta: Path) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(COLUMNAS)
        w.writerows(_fila(l) for l in lecturas)
    return ruta


def escribir_json(lecturas: Iterable[Lectura], ruta: Path) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps([l.a_dict() for l in lecturas], ensure_ascii=False, indent=2), encoding="utf-8")
    return ruta
