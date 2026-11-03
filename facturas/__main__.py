"""Agente de facturas.

Trabajo diario (todo queda en la base de datos facturas_datos/facturas.db):
    python -m facturas procesar FACTURA_O_CARPETA ... [--remitente a@b.com] [--lector local|ollama|gemini|claude|simulado]
    python -m facturas correo                       # baja los adjuntos nuevos del buzón y los procesa
    python -m facturas vigilar CARPETA [--cada 10]  # procesa lo que vaya llegando a una carpeta (Ctrl+C para parar)

Revisión (el gestor):
    python -m facturas hoja                         # escribe revision.csv desde la base, para abrir en Excel
    python -m facturas sincronizar                  # lee revision.csv y guarda lo que el gestor cambió/confirmó
    python -m facturas confirmar ID [--cuenta 62900000]
    python -m facturas cuentas                      # cuentas contables aprendidas por proveedor
    python -m facturas exportar [--incluir-listas]  # CSV de importación con las confirmadas

Medir un lector con vuestras facturas (sin base de datos):
    python -m facturas leer CARPETA --salida resultados [--lector ...]
    python -m facturas comparar CARPETA/esperado.json resultados/resultado.json
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

from . import comparar, config, hoja, pipeline
from .almacen import Almacen
from .extraccion.modelos import ERROR, LISTA, REVISAR
from .extraccion.procesar import archivos_de, procesar_archivo
from .extraccion.proveedor import LECTORES, crear_proveedor
from .extraccion.tabla import escribir_csv, escribir_json


def _progreso(i: int, n: int, ruta: Path) -> None:
    print(f"[{i}/{n}] {ruta.name} ...", flush=True)


def _resumen(filas: list[dict]) -> None:
    for f in filas:
        print(f"  #{f['id']:<4} {f['estado']:<9} {Path(f['archivo']).name}")
        if f["estado"] == ERROR:
            print(f"             ! {f['error']}\n               Qué hacer: {f['que_hacer']}")
        elif f["a_revisar"]:
            for parte in f["a_revisar"].split(" | "):
                print(f"             - {parte}")
    n = Counter(f["estado"] for f in filas)
    print("\n" + " · ".join(f"{k}: {v}" for k, v in sorted(n.items())))


def _leer(a: argparse.Namespace) -> int:
    if not a.carpeta.is_dir():
        print(f"ERROR: no existe la carpeta {a.carpeta}", file=sys.stderr)
        return 2
    proveedor = crear_proveedor(a.lector or config.LECTOR, a.modelo)
    archivos = archivos_de(a.carpeta)
    lecturas = []
    for i, r in enumerate(archivos, 1):
        _progreso(i, len(archivos), r)
        lecturas.append(procesar_archivo(r, proveedor))
    csv_ruta = escribir_csv(lecturas, a.salida / "resultado.csv")
    json_ruta = escribir_json(lecturas, a.salida / "resultado.json")
    n = Counter(l.estado for l in lecturas)
    print(f"Recibidas: {len(lecturas)} | listas: {n[LISTA]} | a revisar: {n[REVISAR]} | con error: {n[ERROR]}")
    print(f"Tabla: {csv_ruta}\nDetalle: {json_ruta}")
    return 0


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="facturas", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("procesar", help="procesa facturas sueltas o carpetas")
    a.add_argument("rutas", nargs="+", type=Path)
    a.add_argument("--remitente", default="")
    a.add_argument("--lector", choices=LECTORES)
    a.add_argument("--reprocesar", action="store_true", help="vuelve a leer aunque el archivo ya se haya leído")

    c = sub.add_parser("correo", help="procesa los adjuntos de correos nuevos (IMAP)")
    c.add_argument("--lector", choices=LECTORES)

    v = sub.add_parser("vigilar", help="procesa lo que vaya llegando a una carpeta")
    v.add_argument("carpeta", type=Path)
    v.add_argument("--cada", type=float, default=10, help="segundos entre comprobaciones (por defecto 10)")
    v.add_argument("--remitente", default="")
    v.add_argument("--lector", choices=LECTORES)

    sub.add_parser("hoja", help="escribe revision.csv desde la base de datos")
    sub.add_parser("sincronizar", help="guarda en la base lo cambiado en revision.csv")

    f = sub.add_parser("confirmar", help="da por buena una factura (y aprende su cuenta contable)")
    f.add_argument("id", type=int)
    f.add_argument("--cuenta", help="cuenta contable de esta factura")

    sub.add_parser("cuentas", help="lista las cuentas aprendidas por proveedor")

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
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.cmd == "leer":
        try:
            return _leer(args)
        except (RuntimeError, ValueError) as e:  # falta una clave, lector desconocido...
            print(f"ERROR: {e}", file=sys.stderr)
            return 2
    if args.cmd == "comparar":
        return comparar.main([str(args.esperado), str(args.resultado)])

    almacen = Almacen()
    try:
        if args.cmd == "procesar":
            filas = pipeline.procesar_rutas(args.rutas, almacen, args.remitente, args.lector, args.reprocesar, _progreso)
            _resumen(filas)
        elif args.cmd == "correo":
            filas = pipeline.procesar_correo(almacen, args.lector, _progreso)
            _resumen(filas) if filas else print("Sin facturas nuevas en el buzón.")
        elif args.cmd == "vigilar":
            print(f"Vigilando {args.carpeta} cada {args.cada:g} s. Ctrl+C para parar.")
            try:
                pipeline.vigilar(args.carpeta, almacen, args.lector, args.cada, args.remitente, _progreso, _resumen)
            except KeyboardInterrupt:
                print("\nParado.")
        elif args.cmd == "hoja":
            print(f"{hoja.escribir_hoja(almacen)} facturas escritas en {config.REVISION}")
        elif args.cmd == "sincronizar":
            r = hoja.sincronizar(almacen)
            print(f"{r['modificadas']} facturas modificadas, {r['confirmadas']} confirmadas")
            for aviso in r["ignoradas"]:
                print(f"  ignorado: {aviso}")
        elif args.cmd == "confirmar":
            f = almacen.confirmar(args.id, args.cuenta)
            c = almacen.cuenta_de(f["nif_proveedor"])
            print(f"#{f['id']} confirmada." + (f" Cuenta {c['cuenta']}: confirmada {c['confirmaciones']} veces." if c else " (sin cuenta: nada que aprender)"))
        elif args.cmd == "cuentas":
            filas = almacen.db.execute("SELECT * FROM cuentas ORDER BY proveedor").fetchall()
            for c in filas:
                estado = "fiable" if c["confirmaciones"] >= config.CONFIRMACIONES_CUENTA else "sugerida"
                print(f"  {c['nif']:<11} {c['proveedor'] or '?':<32} {c['cuenta']:<10} {c['confirmaciones']} conf. ({estado})")
            if not filas:
                print("Todavía no se ha aprendido ninguna cuenta.")
        elif args.cmd == "exportar":
            print(f"{hoja.exportar(almacen, args.incluir_listas)} facturas exportadas a {config.IMPORTACION}")
    except (RuntimeError, ValueError) as e:  # falta una clave, buzón sin configurar, id inexistente...
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    finally:
        almacen.cerrar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
