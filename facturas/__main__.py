"""Agente de facturas.

Producción (deja las facturas en la hoja de revisión):
    python -m facturas procesar FACTURA_O_CARPETA ... [--remitente a@b.com] [--lector local|ollama|gemini|claude|simulado]
    python -m facturas correo                      # baja los adjuntos nuevos del buzón y los procesa
    python -m facturas exportar [--incluir-listas] # CSV de importación con las confirmadas

Medir (sin hoja ni duplicados; sirve para ajustar el lector con vuestras facturas):
    python -m facturas leer CARPETA --salida resultados [--lector ...]
    python -m facturas comparar CARPETA/esperado.json resultados/resultado.json
"""
import argparse
import logging
import sys
from collections import Counter
from pathlib import Path

from . import comparar, config, hoja, pipeline
from .extraccion.modelos import ERROR, LISTA, REVISAR
from .extraccion.procesar import procesar_carpeta
from .extraccion.proveedor import LECTORES, crear_proveedor
from .extraccion.tabla import escribir_csv, escribir_json


def _resumen(f: dict) -> str:
    print(f"  {f['estado']:<9} {Path(f['archivo']).name}")
    if f["estado"] == ERROR:
        print(f"             ! {f['error']}\n               Qué hacer: {f['que_hacer']}")
    elif f["a_revisar"]:
        for parte in f["a_revisar"].split(" | "):
            print(f"             - {parte}")
    return f["estado"]


def _leer(a: argparse.Namespace) -> int:
    if not a.carpeta.is_dir():
        print(f"ERROR: no existe la carpeta {a.carpeta}", file=sys.stderr)
        return 2
    lecturas = procesar_carpeta(a.carpeta, crear_proveedor(a.lector or config.LECTOR, a.modelo))
    csv_ruta = escribir_csv(lecturas, a.salida / "resultado.csv")
    json_ruta = escribir_json(lecturas, a.salida / "resultado.json")
    n = Counter(l.estado for l in lecturas)
    print(f"Recibidas: {len(lecturas)} | listas: {n[LISTA]} | a revisar: {n[REVISAR]} | con error: {n[ERROR]}")
    print(f"Tabla: {csv_ruta}\nDetalle: {json_ruta}")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser(prog="facturas", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("procesar", help="procesa facturas sueltas o carpetas y las deja en la hoja")
    a.add_argument("rutas", nargs="+", type=Path)
    a.add_argument("--remitente", default="")
    a.add_argument("--lector", choices=LECTORES)

    c = sub.add_parser("correo", help="procesa los adjuntos de correos nuevos (IMAP)")
    c.add_argument("--lector", choices=LECTORES)

    e = sub.add_parser("exportar", help="genera el CSV de importación")
    e.add_argument("--incluir-listas", action="store_true", help="exporta también las `lista` sin revisión humana")

    m = sub.add_parser("leer", help="lee una carpeta y escribe resultado.csv/json (para medir)")
    m.add_argument("carpeta", type=Path)
    m.add_argument("--salida", type=Path, default=Path("resultados"))
    m.add_argument("--lector", choices=LECTORES)
    m.add_argument("--modelo")

    k = sub.add_parser("comparar", help="mide el acierto frente a esperado.json")
    k.add_argument("esperado", type=Path)
    k.add_argument("resultado", type=Path)

    args = p.parse_args(argv)
    try:
        if args.cmd == "leer":
            return _leer(args)
        if args.cmd == "comparar":
            return comparar.main([str(args.esperado), str(args.resultado)])
        if args.cmd == "exportar":
            n = hoja.exportar(incluir_listas=args.incluir_listas)
            print(f"{n} facturas exportadas a {config.IMPORTACION}")
            return 0
        filas = (pipeline.procesar_rutas(args.rutas, args.remitente, args.lector) if args.cmd == "procesar"
                 else pipeline.procesar_correo(args.lector))
    except (RuntimeError, ValueError) as e:  # falta una clave, buzón sin configurar...
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    if not filas:
        print("Sin facturas nuevas.")
    for f in filas:
        _resumen(f)
    print(f"\nHoja de revisión: {config.REVISION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
