"""Uso:
    python -m facturas procesar FACTURA.pdf [--remitente a@b.com] [--extractor gemini|claude|simulado]
    python -m facturas correo                 # baja los adjuntos nuevos del buzón y los procesa
    python -m facturas exportar [--incluir-listas]
"""
import argparse
import logging
from pathlib import Path

from . import config, hoja, pipeline


def _resumen(f: dict) -> str:
    return f"[{f['estado']:<8}] {Path(f['archivo']).name}  {f.get('proveedor') or '?'}  total={f.get('total') or '?'}  {f['motivos']}"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser(prog="facturas")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("procesar", help="procesa archivos de factura sueltos")
    a.add_argument("archivos", nargs="+", type=Path)
    a.add_argument("--remitente", default="")
    a.add_argument("--extractor", choices=["gemini", "claude", "simulado"])

    c = sub.add_parser("correo", help="procesa los adjuntos de correos nuevos (IMAP)")
    c.add_argument("--extractor", choices=["gemini", "claude", "simulado"])

    e = sub.add_parser("exportar", help="genera el CSV de importación")
    e.add_argument("--incluir-listas", action="store_true", help="exporta también las que pasaron todas las validaciones sin revisión humana")

    args = p.parse_args()
    if args.cmd == "procesar":
        filas = [pipeline.procesar_archivo(r, args.remitente, args.extractor) for r in args.archivos]
    elif args.cmd == "correo":
        filas = pipeline.procesar_correo(args.extractor)
        if not filas:
            print("Sin facturas nuevas en el buzón.")
    else:
        n = hoja.exportar(incluir_listas=args.incluir_listas)
        print(f"{n} facturas exportadas a {config.IMPORTACION}")
        return
    for f in filas:
        print(_resumen(f))
    print(f"\nHoja de revisión: {config.REVISION}")


if __name__ == "__main__":
    main()
