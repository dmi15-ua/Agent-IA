"""Genera un juego de facturas FICTICIAS de diseños distintos, con su esperado.json.

    python facturas/generar_ejemplos.py

Cada factura se define una sola vez (texto + posición) y se vuelca a PDF digital, a PDF escaneado
o a una "foto de móvil" simulada (giro, sombra, desenfoque, ruido, JPEG). Los valores correctos
salen de los mismos datos, así que esperado.json no puede desincronizarse.

OJO: son facturas inventadas y fotos simuladas. Sirven para detectar fallos genéricos, no
sustituyen a facturas reales de proveedores reales.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from facturas.extraccion.nif import _control_cif, _LETRAS_DNI  # noqa: E402

SALIDA = Path(__file__).parent / "ejemplos_variados"
W, H = 595, 842
FUENTE = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FUENTE_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


# ---------------------------------------------------------------- NIF válidos para los datos de prueba
def cif(letra: str, cuerpo: str) -> str:
    c = _control_cif(cuerpo)
    return f"{letra}{cuerpo}{c if letra in 'ABEH' else 'JABCDEFGHI'[c]}"


def dni(n: int) -> str:
    return f"{n:08d}{_LETRAS_DNI[n % 23]}"


def nie(letra: str, n: int) -> str:
    return f"{letra}{n:07d}" + _LETRAS_DNI[int(str('XYZ'.index(letra)) + f'{n:07d}') % 23]


def eur(x: float, simbolo: str = " €") -> str:
    s = f"{abs(x):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-" if x < 0 else "") + s + simbolo


CLIENTE, NIF_CLIENTE = "Cliente Demo S.L.", cif("B", "8765432")


# ---------------------------------------------------------------- diseños: devuelven [(x, y_desde_arriba, tamaño, negrita, texto)]
def estandar(d: dict, idioma: str = "es", dos_columnas: bool = False) -> list:
    en = idioma == "en"
    t = {"factura": "INVOICE" if en else "FACTURA", "num": "Invoice No" if en else "Nº", "fecha": "Date" if en else "Fecha",
         "cli": "Bill to:" if en else "Facturar a:", "base": "Subtotal" if en else "Base imponible",
         "iva": "VAT" if en else "IVA", "total": "TOTAL DUE" if en else "TOTAL FACTURA", "irpf": "IRPF withholding" if en else "Retención IRPF"}
    it = [(56, 50, 15, True, d["prov"]), (56, 70, 10, False, f"{'VAT' if en else 'NIF'}: {d['nif_p']}"), (56, 85, 10, False, d.get("dir", "Calle Inventada 1, Madrid")),
          (380, 50, 18, True, t["factura"]), (380, 74, 11, False, f"{t['num']}: {d['num']}"), (380, 90, 11, False, f"{t['fecha']}: {d['fecha_txt']}")]
    xc, yc = (320, 130) if dos_columnas else (56, 140)
    it += [(xc, yc, 10, True, t["cli"]), (xc, yc + 15, 11, False, d.get("cliente", CLIENTE)), (xc, yc + 30, 10, False, f"{'VAT' if en else 'NIF'}: {d.get('nif_c', NIF_CLIENTE)}")]
    y = 215
    it.append((56, y, 10, True, "Concepto" if not en else "Description")); it.append((470, y, 10, True, "Importe" if not en else "Amount"))
    for desc, imp in d["lineas"]:
        y += 18
        it += [(56, y, 10, False, desc), (470, y, 10, False, eur(imp))]
    y += 50
    for etiqueta, importe in d["totales"]:
        negrita = etiqueta.startswith(t["total"])
        it += [(330, y, 11, negrita, etiqueta), (470, y, 11, negrita, importe)]
        y += 18
    return it + [(56, 790, 8, False, d.get("pie", "Inscrita en el Registro Mercantil de Madrid. Datos ficticios para pruebas."))]


def ticket(d: dict) -> list:
    it = [(150, 60, 14, True, d["prov"]), (150, 80, 10, False, f"CIF: {d['nif_p']}"), (150, 94, 10, False, "C/ Falsa 123 - Valencia"),
          (150, 125, 11, True, "FACTURA SIMPLIFICADA"), (150, 141, 10, False, f"Nº: {d['num']}"), (150, 155, 10, False, f"Fecha: {d['fecha_txt']}")]
    y = 190
    for desc, imp in d["lineas"]:
        it += [(150, y, 10, False, desc), (330, y, 10, False, eur(imp))]
        y += 16
    y += 20
    for etiqueta, importe in d["totales"]:
        it += [(150, y, 11, etiqueta.startswith("TOTAL"), etiqueta), (330, y, 11, etiqueta.startswith("TOTAL"), importe)]
        y += 17
    return it + [(150, y + 30, 9, False, "Gracias por su visita")]


# ---------------------------------------------------------------- volcado a PDF y a imagen
def a_pdf(items: list, destino: Path) -> None:
    cont = []
    for x, y, tam, neg, txt in items:
        e = txt.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").replace("€", "\\200").replace("£", "\\243")
        cont.append(f"BT /{'F2' if neg else 'F1'} {tam} Tf {x} {H - y - tam} Td ({e}) Tj ET")
    flujo = "\n".join(cont).encode("latin-1", "replace")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(flujo) + flujo + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"]
    out, pos = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        pos.append(len(out)); out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % p for p in pos)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    destino.write_bytes(out)


def a_imagen(items: list, escala: float = 2.0) -> Image.Image:
    img = Image.new("RGB", (int(W * escala), int(H * escala)), (252, 252, 250))
    d = ImageDraw.Draw(img)
    for x, y, tam, neg, txt in items:
        d.text((x * escala, y * escala), txt, fill=(25, 25, 25), font=ImageFont.truetype(FUENTE_B if neg else FUENTE, int(tam * escala * 0.95)))
    return img


def foto(img: Image.Image, seed: int, angulo: float = 0, sombra: float = 0, desenfoque: float = 0, ruido: float = 4, ancho: int = 1100, q: int = 72) -> Image.Image:
    """Simula una foto de móvil: mesa de fondo, giro, sombra, desenfoque, ruido y JPEG."""
    rng = np.random.default_rng(seed)
    fondo = Image.new("RGB", (int(img.width * 1.25), int(img.height * 1.12)), (118, 96, 74))
    fondo = Image.fromarray(np.clip(np.asarray(fondo) + rng.normal(0, 7, (fondo.height, fondo.width, 1)), 0, 255).astype("uint8"))
    papel = img.rotate(angulo, expand=True, resample=Image.BICUBIC, fillcolor=(118, 96, 74))
    fondo.paste(papel, ((fondo.width - papel.width) // 2, (fondo.height - papel.height) // 2))
    a = np.asarray(fondo).astype("float32")
    if sombra:
        yy, xx = np.mgrid[0:a.shape[0], 0:a.shape[1]]
        gradiente = 1 - sombra * np.clip((xx / a.shape[1]) * 0.8 + (yy / a.shape[0]) * 0.4, 0, 1)
        a *= gradiente[..., None]
    a += rng.normal(0, ruido, a.shape)
    out = Image.fromarray(np.clip(a, 0, 255).astype("uint8"))
    if desenfoque:
        out = out.filter(ImageFilter.GaussianBlur(desenfoque))
    return out.resize((ancho, int(out.height * ancho / out.width)), Image.LANCZOS)


# ---------------------------------------------------------------- las facturas
def datos() -> list[dict]:
    N_ESTANDAR = {"prov": "Suministros Ficticios S.L.", "nif_p": cif("B", "1234567"), "num": "2026-0042", "fecha": "2026-10-15",
                  "fecha_txt": "15/10/2026", "lineas": [("Material de oficina", 100.00)],
                  "totales": [("Base imponible", eur(100)), ("IVA 21%", eur(21)), ("TOTAL FACTURA", eur(121))],
                  "esp": {"base_imponible": 100.0, "cuota_iva": 21.0, "total": 121.0}}
    F = []

    def add(nombre, tipo, d, **kw):
        d = {**d, "nombre": nombre, "tipo": tipo, **kw}
        esp = {"numero_factura": d["num"], "fecha_expedicion": d["fecha"], "proveedor": d["prov"], "nif_proveedor": d["nif_p"], **d["esp"]}
        if tipo not in ("ticket",):
            esp["nif_cliente"] = d.get("nif_c", NIF_CLIENTE)
        d["esperado"] = esp
        F.append(d)

    add("01_estandar_sl", "digital", N_ESTANDAR)
    add("02_dos_tipos_de_iva", "digital", {**N_ESTANDAR, "prov": "Papelería y Más S.A.", "nif_p": cif("A", "2345678"), "num": "PM-310", "fecha": "2026-09-03", "fecha_txt": "03/09/2026",
        "lineas": [("Cuadernos y bolígrafos", 100.00), ("Libros de texto", 50.00)],
        "totales": [("Base imponible 21%", eur(100)), ("IVA 21%", eur(21)), ("Base imponible 10%", eur(50)), ("IVA 10%", eur(5)), ("TOTAL FACTURA", eur(176))],
        "esp": {"base_imponible": 150.0, "cuota_iva": 26.0, "total": 176.0}})
    add("03_autonomo_con_irpf", "digital", {**N_ESTANDAR, "prov": "María López Ruiz", "nif_p": dni(12345678), "num": "A/2026/17", "fecha": "2026-10-01", "fecha_txt": "01/10/2026",
        "lineas": [("Servicios de diseño gráfico", 200.00)], "dir": "Av. de la Paz 8, Sevilla",
        "totales": [("Base imponible", eur(200)), ("IVA 21%", eur(42)), ("Retención IRPF 15%", eur(-30)), ("TOTAL FACTURA", eur(212))],
        "esp": {"base_imponible": 200.0, "cuota_iva": 42.0, "retencion_irpf": 30.0, "total": 212.0}})
    add("04_iva_superreducido_4", "digital", {**N_ESTANDAR, "prov": "Panadería La Espiga C.B.", "nif_p": cif("E", "3456789"), "num": "0098", "fecha": "2026-10-20", "fecha_txt": "20/10/2026",
        "lineas": [("Pan y harinas", 80.00)], "totales": [("Base imponible", eur(80)), ("IVA 4%", eur(3.20)), ("TOTAL FACTURA", eur(83.20))],
        "esp": {"base_imponible": 80.0, "cuota_iva": 3.2, "total": 83.2}})
    add("05_exenta_de_iva", "digital", {**N_ESTANDAR, "prov": "Academia Saber S.L.", "nif_p": cif("B", "4567890"), "num": "F-2026-221", "fecha": "2026-08-30", "fecha_txt": "30/08/2026",
        "lineas": [("Curso de formación (exento art. 20 LIVA)", 150.00)], "totales": [("Base imponible", eur(150)), ("IVA 0% (exento)", eur(0)), ("TOTAL FACTURA", eur(150))],
        "esp": {"base_imponible": 150.0, "cuota_iva": 0.0, "total": 150.0}})
    add("06_rectificativa_negativa", "digital", {**N_ESTANDAR, "prov": "Suministros Ficticios S.L.", "num": "R-2026-0007", "fecha": "2026-10-25", "fecha_txt": "25/10/2026",
        "lineas": [("Abono de la factura 2026-0042", -100.00)], "totales": [("Base imponible", eur(-100)), ("IVA 21%", eur(-21)), ("TOTAL FACTURA", eur(-121))],
        "esp": {"base_imponible": -100.0, "cuota_iva": -21.0, "total": -121.0}})
    add("07_fecha_en_texto", "digital", {**N_ESTANDAR, "prov": "Limpiezas Brillo S.L.", "nif_p": cif("B", "5678901"), "num": "L-455", "fecha": "2026-10-15", "fecha_txt": "15 de octubre de 2026",
        "lineas": [("Servicio de limpieza mensual", 300.00)], "totales": [("Base imponible", eur(300)), ("IVA 21%", eur(63)), ("TOTAL FACTURA", eur(363))],
        "esp": {"base_imponible": 300.0, "cuota_iva": 63.0, "total": 363.0}})
    add("08_importes_con_miles", "digital", {**N_ESTANDAR, "prov": "Maquinaria Pesada S.A.", "nif_p": cif("A", "6789012"), "num": "2026/1188", "fecha": "2026-07-12", "fecha_txt": "12/07/2026",
        "lineas": [("Alquiler de excavadora", 1234.56)], "totales": [("Base imponible", eur(1234.56)), ("IVA 21%", eur(259.26)), ("TOTAL FACTURA", eur(1493.82))],
        "esp": {"base_imponible": 1234.56, "cuota_iva": 259.26, "total": 1493.82}})
    add("09_dos_columnas", "digital", {**N_ESTANDAR, "prov": "Informática del Sur S.L.", "nif_p": cif("B", "7890123"), "num": "IS-9001", "fecha": "2026-09-18", "fecha_txt": "18/09/2026",
        "lineas": [("Mantenimiento de equipos", 450.00)], "totales": [("Base imponible", eur(450)), ("IVA 21%", eur(94.50)), ("TOTAL FACTURA", eur(544.50))],
        "esp": {"base_imponible": 450.0, "cuota_iva": 94.5, "total": 544.5}}, dos_columnas=True)
    add("10_plantilla_en_ingles", "digital", {**N_ESTANDAR, "prov": "Global Tech Services S.L.", "nif_p": cif("B", "8901234"), "num": "INV-3321", "fecha": "2026-10-05", "fecha_txt": "2026-10-05",
        "lineas": [("Cloud hosting", 600.00)], "totales": [("Subtotal", eur(600)), ("VAT 21%", eur(126)), ("TOTAL DUE", eur(726))],
        "esp": {"base_imponible": 600.0, "cuota_iva": 126.0, "total": 726.0}}, idioma="en")
    add("11_extranjera_francia", "digital", {**N_ESTANDAR, "prov": "Atelier Lumière SARL", "nif_p": "FR40303265045", "num": "FA-2026-118", "fecha": "2026-10-10", "fecha_txt": "10/10/2026",
        "lineas": [("Prestation de conseil (autoliquidación IVA)", 500.00)], "dir": "12 Rue de la Paix, Paris",
        "totales": [("Base imponible", eur(500)), ("IVA 0% (inversión sujeto pasivo)", eur(0)), ("TOTAL FACTURA", eur(500))],
        "esp": {"base_imponible": 500.0, "cuota_iva": 0.0, "total": 500.0}})
    add("12_extranjera_libras", "digital", {**N_ESTANDAR, "prov": "Thames Consulting Ltd", "nif_p": "GB123456789", "num": "TC-0456", "fecha": "2026-09-28", "fecha_txt": "28/09/2026",
        "lineas": [("Consulting services", 800.00)], "dir": "1 London Road, London",
        "totales": [("Subtotal", "800,00 £"), ("VAT 0%", "0,00 £"), ("TOTAL", "800,00 £")],
        "esp": {"base_imponible": 800.0, "cuota_iva": 0.0, "total": 800.0}}, idioma="en")
    add("13_con_descuento", "digital", {**N_ESTANDAR, "prov": "Ferretería Industrial S.L.", "nif_p": cif("B", "9012345"), "num": "FI-7720", "fecha": "2026-10-22", "fecha_txt": "22/10/2026",
        "lineas": [("Tornillería y herrajes", 400.00), ("Descuento 10%", -40.00)],
        "totales": [("Subtotal", eur(400)), ("Descuento 10%", eur(-40)), ("Base imponible", eur(360)), ("IVA 21%", eur(75.60)), ("TOTAL FACTURA", eur(435.60))],
        "esp": {"base_imponible": 360.0, "cuota_iva": 75.6, "total": 435.6}})
    add("14_ticket_simplificado", "ticket", {"prov": "Bar Los Amigos S.L.", "nif_p": cif("B", "0123456"), "num": "T-88213", "fecha": "2026-10-12", "fecha_txt": "12/10/2026",
        "lineas": [("2 x Menú del día", 36.00), ("2 x Café", 4.00), ("1 x Agua", 1.10)],
        "totales": [("Base imponible", eur(37.36)), ("IVA 10%", eur(3.74)), ("TOTAL", eur(41.10))],
        "esp": {"base_imponible": 37.36, "cuota_iva": 3.74, "total": 41.10}})
    # La misma factura estándar, en otros formatos:
    add("15_escaneado_pdf", "escaneado", {**N_ESTANDAR, "prov": "Transportes Rápidos S.L.", "nif_p": cif("B", "1122334"), "num": "TR-5512", "fecha": "2026-10-08", "fecha_txt": "08/10/2026",
        "lineas": [("Transporte de mercancías", 250.00)], "totales": [("Base imponible", eur(250)), ("IVA 21%", eur(52.50)), ("TOTAL FACTURA", eur(302.50))],
        "esp": {"base_imponible": 250.0, "cuota_iva": 52.5, "total": 302.5}})
    base_foto = {**N_ESTANDAR, "prov": "Electricidad Hnos. Gómez S.L.", "nif_p": cif("B", "2233445"), "num": "EG-2026-64", "fecha": "2026-10-14", "fecha_txt": "14/10/2026",
                 "lineas": [("Instalación eléctrica", 320.00)], "totales": [("Base imponible", eur(320)), ("IVA 21%", eur(67.20)), ("TOTAL FACTURA", eur(387.20))],
                 "esp": {"base_imponible": 320.0, "cuota_iva": 67.2, "total": 387.2}}
    add("16_foto_recta", "foto", base_foto, foto_args=dict(seed=1, angulo=0, sombra=0, desenfoque=0.5, ruido=3))
    add("17_foto_torcida_5_grados", "foto", base_foto, foto_args=dict(seed=2, angulo=5, sombra=0, desenfoque=0.7, ruido=4))
    add("18_foto_con_sombra", "foto", base_foto, foto_args=dict(seed=3, angulo=1.5, sombra=0.45, desenfoque=0.7, ruido=5))
    add("19_foto_torcida_sombra_borrosa", "foto", base_foto, foto_args=dict(seed=4, angulo=-9, sombra=0.5, desenfoque=1.3, ruido=7))
    add("20_foto_baja_resolucion", "foto", base_foto, foto_args=dict(seed=5, angulo=3, sombra=0.2, desenfoque=0.9, ruido=6, ancho=720, q=55))
    return F


def main() -> None:
    SALIDA.mkdir(exist_ok=True)
    for f in SALIDA.glob("*"):
        if f.is_file():
            f.unlink()
    esperado = {}
    for d in datos():
        n, tipo = d["nombre"], d["tipo"]
        items = ticket(d) if tipo == "ticket" else estandar(d, d.get("idioma", "es"), d.get("dos_columnas", False))
        if tipo in ("digital", "ticket"):
            archivo = f"{n}.pdf"; a_pdf(items, SALIDA / archivo)
        elif tipo == "escaneado":
            archivo = f"{n}.pdf"; a_imagen(items, 1.8).convert("L").save(SALIDA / archivo, resolution=130)
        else:
            archivo = f"{n}.jpg"; foto(a_imagen(items), **d["foto_args"]).save(SALIDA / archivo, quality=d["foto_args"].get("q", 72))
        esperado[archivo] = d["esperado"]
    a_pdf([(56, 60, 18, True, "Restaurante El Buen Comer"), (56, 90, 11, False, "Menú del día"), (56, 110, 10, False, "Primeros: ensalada, sopa"), (56, 125, 10, False, "Segundos: pescado, carne"), (56, 140, 10, False, "Precio: 12,50 €")],
          SALIDA / "21_no_es_factura_menu.pdf")
    (SALIDA / "esperado.json").write_text(json.dumps(esperado, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(esperado) + 1} documentos en {SALIDA}")


if __name__ == "__main__":
    main()
