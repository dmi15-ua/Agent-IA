"""Tests del agente de facturas. Sin red ni API key.

    python -m unittest facturas.test_facturas -v
"""
import json
import shutil
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path
from unittest import mock

import csv
import os

from . import __main__ as cli
from . import comparar, config, hoja, ingesta, pipeline
from .almacen import Almacen
from .extraccion import imagen, nif, procesar, proveedor
from .extraccion.lector_local import LectorLocal
from .extraccion.modelos import ERROR, LISTA, REVISAR
from .extraccion.reglas_texto import _fechas, extraer

EJEMPLOS = Path(__file__).parent / "ejemplos"
PDF_TEXTO = EJEMPLOS / "factura_texto.pdf"
VARIADOS = Path(__file__).parent / "ejemplos_variados"
HAY_PDFTOTEXT = shutil.which("pdftotext") is not None
HAY_TESSERACT = shutil.which("tesseract") is not None


def c(valor, legible="claro", motivo=""):
    return {"valor": valor, "legible": legible, "motivo": motivo}


def respuesta(**cambios) -> dict:
    campos = {
        "numero_factura": c("2026-0042"), "fecha_expedicion": c("2026-10-15"),
        "proveedor": c("Suministros Ficticios S.L."), "nif_proveedor": c("B12345674"),
        "cliente": c("Cliente Demo S.L."), "nif_cliente": c("B87654323"),
        "base_imponible": c(100.0), "cuota_iva": c(21.0), "total": c(121.0),
        "retencion_irpf": c(None), "descripcion": c(None), "moneda": c("EUR"),
    }
    campos.update(cambios)
    return {"es_factura": True, "campos": campos,
            "desglose_iva": [{"tipo": 21, "base": 100.0, "cuota": 21.0}]}


class Falso:
    """Proveedor que devuelve lo que se le diga."""

    def __init__(self, datos):
        self.datos = datos

    def leer(self, ruta, instruccion):
        return json.dumps(self.datos)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.pdf = self.tmp / "f.pdf"
        self.pdf.write_bytes(b"%PDF-1.4 ficticio")
        self.hoja = self.tmp / "revision.csv"

    def leer(self, datos, ruta=None):
        return procesar.procesar_archivo(ruta or self.pdf, Falso(datos))


class TestComprobaciones(Base):
    def test_factura_correcta(self):
        self.assertEqual(self.leer(respuesta()).estado, LISTA)

    def test_base_mas_iva_no_suma(self):
        l = self.leer(respuesta(total=c(130.0)))
        self.assertEqual(l.estado, REVISAR)
        self.assertIn("no suma el total", l.campos["total"].motivo)

    def test_retencion_irpf_no_da_falso_positivo(self):
        # autónomo: 100 + 21 - 15 = 106
        l = self.leer(respuesta(total=c(106.0), retencion_irpf=c(15.0)))
        self.assertEqual(l.estado, LISTA)

    def test_nif_fecha_futura_y_tipo_de_iva(self):
        self.assertIn("campos", self.leer(respuesta()).a_dict())
        self.assertEqual(self.leer(respuesta(nif_proveedor=c("1234"))).estado, REVISAR)
        self.assertEqual(self.leer(respuesta(fecha_expedicion=c("2999-01-01"))).estado, REVISAR)
        raro = respuesta()
        raro["desglose_iva"] = [{"tipo": 13, "base": 100.0, "cuota": 13.0}]
        self.assertEqual(self.leer(raro).estado, REVISAR)

    def test_campo_ilegible_queda_vacio_y_va_a_revisar(self):
        l = self.leer(respuesta(base_imponible=c(None, "ilegible", "tachón")))
        self.assertEqual((l.estado, l.campos["base_imponible"].valor), (REVISAR, None))

    def test_no_es_factura_es_error_explicado(self):
        l = self.leer({"es_factura": False})
        self.assertEqual(l.estado, ERROR)
        self.assertTrue(l.que_hacer)

    def test_entran_n_salen_n(self):
        for n in ("a.pdf", "b.png", "c.xyz", "vacio.pdf"):
            (self.tmp / n).write_bytes(b"" if n == "vacio.pdf" else b"x")
        (self.tmp / "esperado.json").write_text("{}")
        lecturas = procesar.procesar_carpeta(self.tmp, Falso({"es_factura": False}))
        # f.pdf + a + b + c + vacio; esperado.json no cuenta
        self.assertEqual(len(lecturas), 5)
        self.assertTrue(all(l.estado == ERROR for l in lecturas))

    def test_json_basura_no_rompe(self):
        class Basura:
            def leer(self, r, i):
                return "lo siento, no puedo"

        self.assertEqual(procesar.procesar_archivo(self.pdf, Basura()).estado, ERROR)


@unittest.skipUnless(HAY_PDFTOTEXT, "falta pdftotext (poppler-utils)")
class TestLecturaReal(Base):
    def test_lector_local_lee_un_pdf_con_texto(self):
        l = procesar.procesar_archivo(PDF_TEXTO, LectorLocal())
        self.assertEqual(l.estado, LISTA, l.campos_a_revisar())
        v = {n: x.valor for n, x in l.campos.items()}
        self.assertEqual((v["numero_factura"], v["fecha_expedicion"], v["nif_proveedor"], v["total"]),
                         ("2026-0042", "2026-10-15", "B12345674", 121.0))

    def test_un_dato_inventado_por_el_modelo_se_detecta(self):
        # El modelo "lee" un total y un número que NO están en el PDF y los da por claros.
        inventado = respuesta(total=c(999.0), base_imponible=c(825.62), cuota_iva=c(173.38),
                              numero_factura=c("2026-9999"))
        inventado["desglose_iva"] = [{"tipo": 21, "base": 825.62, "cuota": 173.38}]
        l = procesar.procesar_archivo(PDF_TEXTO, proveedor.ProveedorVerificado(Falso(inventado)))
        self.assertEqual(l.estado, REVISAR)
        for n in ("total", "numero_factura"):
            self.assertIn("no aparece", l.campos[n].motivo, n)

    def test_un_dato_correcto_pasa_la_verificacion(self):
        l = procesar.procesar_archivo(PDF_TEXTO, proveedor.ProveedorVerificado(Falso(respuesta())))
        self.assertEqual(l.estado, LISTA, [(n, l.campos[n].motivo) for n in l.campos_a_revisar()])

    def test_sin_texto_la_verificacion_no_bloquea(self):
        # self.pdf no es un PDF real: no se puede verificar, la respuesta pasa tal cual
        l = procesar.procesar_archivo(self.pdf, proveedor.ProveedorVerificado(Falso(respuesta())))
        self.assertEqual(l.estado, LISTA)


class TestReglasTexto(unittest.TestCase):
    def test_texto_que_no_es_factura(self):
        self.assertFalse(extraer("Menú del día\nPaella 12,00\nPostre 4,00")["es_factura"])

    def test_nombre_sin_forma_juridica_es_dudoso(self):
        texto = "Juan Pérez García\nNIF: 12345678Z\nFACTURA Nº: A-1\nFecha: 01/10/2026\nBase imponible 10,00\nIVA 21% 2,10\nTOTAL 12,10"
        self.assertEqual(extraer(texto)["campos"]["proveedor"]["legible"], "dudoso")


class TestProveedores(unittest.TestCase):
    def test_gemini_sin_clave(self):
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": ""}):
            with self.assertRaises(RuntimeError):
                proveedor.ProveedorGemini()

    def test_gemini_devuelve_el_texto_y_manda_el_documento(self):
        pdf = Path(tempfile.mkdtemp()) / "f.pdf"
        pdf.write_bytes(b"%PDF")
        r = mock.Mock(status_code=200)
        r.json.return_value = {"candidates": [{"content": {"parts": [{"text": "{\"es_factura\": false}"}]}}]}
        with mock.patch("httpx.post", return_value=r) as post:
            out = proveedor.ProveedorGemini(clave="k").leer(pdf, "instr")
        self.assertEqual(out, '{"es_factura": false}')
        self.assertEqual(post.call_args.kwargs["json"]["contents"][0]["parts"][0]["inline_data"]["mime_type"], "application/pdf")
        self.assertEqual(post.call_args.kwargs["headers"], {"x-goog-api-key": "k"})  # clave en cabecera, no en la URL

    def test_gemini_error_http_no_vuelca_el_cuerpo(self):
        pdf = Path(tempfile.mkdtemp()) / "f.pdf"
        pdf.write_bytes(b"%PDF")
        r = mock.Mock(status_code=429, text="DATOS DE LA FACTURA")
        with mock.patch("httpx.post", return_value=r):
            with self.assertRaises(RuntimeError) as cm:
                proveedor.ProveedorGemini(clave="k").leer(pdf, "i")
        self.assertNotIn("DATOS", str(cm.exception))

    def test_fabrica(self):
        self.assertIsInstance(proveedor.crear_proveedor("simulado"), proveedor.ProveedorSimulado)
        self.assertIsInstance(proveedor.crear_proveedor("local"), LectorLocal)
        with self.assertRaises(ValueError):
            proveedor.crear_proveedor("chatgpt")


class Contador:
    """Proveedor que cuenta cuántas veces se le llama."""

    def __init__(self, datos):
        self.datos, self.llamadas = datos, 0

    def leer(self, ruta, instruccion):
        self.llamadas += 1
        return json.dumps(self.datos)


class BaseAlmacen(Base):
    def setUp(self):
        super().setUp()
        self.db = Almacen(Path(":memory:"))
        self.addCleanup(self.db.cerrar)

    def procesar(self, datos, ruta=None, **kw):
        return pipeline.procesar_archivo(ruta or self.pdf, "p@x.com", Falso(datos), self.db, **kw)

    def otra_factura(self, n, **cambios):
        f = self.tmp / f"f{n}.pdf"
        f.write_bytes(f"%PDF distinto {n}".encode())
        return f, respuesta(numero_factura=c(f"2026-{n:04d}"), **cambios)


class TestAlmacen(BaseAlmacen):
    def test_mismo_archivo_no_se_vuelve_a_leer(self):
        lector = Contador(respuesta())
        a = pipeline.procesar_archivo(self.pdf, "", lector, self.db)
        b = pipeline.procesar_archivo(self.pdf, "", lector, self.db)
        self.assertEqual(lector.llamadas, 1)  # la segunda vez no se llama al lector (ni se paga la API)
        self.assertEqual(b["estado"], "repetida")
        self.assertEqual(b["original_id"], a["id"])
        self.assertIn("Mismo archivo", b["a_revisar"])

    def test_un_error_se_reintenta_aunque_sea_el_mismo_archivo(self):
        lector = Contador({"es_factura": False})
        pipeline.procesar_archivo(self.pdf, "", lector, self.db)
        pipeline.procesar_archivo(self.pdf, "", lector, self.db)
        self.assertEqual(lector.llamadas, 2)  # p. ej. se cayó la red: no se queda "cacheado" el fallo

    def test_reprocesar_fuerza_la_lectura(self):
        lector = Contador(respuesta())
        pipeline.procesar_archivo(self.pdf, "", lector, self.db)
        pipeline.procesar_archivo(self.pdf, "", lector, self.db, reprocesar=True)
        self.assertEqual(lector.llamadas, 2)

    def test_misma_factura_en_otro_archivo_se_detecta_por_clave(self):
        a = self.procesar(respuesta())
        otro = self.tmp / "copia.pdf"
        otro.write_bytes(b"%PDF otro archivo, misma factura")
        b = self.procesar(respuesta(), otro)
        self.assertEqual((b["estado"], b["original_id"]), ("repetida", a["id"]))
        self.assertEqual(a["clave"], "B12345674|2026-0042|12100")

    def test_mismo_numero_con_otro_importe_no_es_duplicado(self):
        self.procesar(respuesta())
        otro = self.tmp / "o.pdf"
        otro.write_bytes(b"%PDF otro")
        r = self.procesar(respuesta(total=c(106.0), retencion_irpf=c(15.0)), otro)
        self.assertNotEqual(r["estado"], "repetida")

    def test_un_error_nunca_cuenta_como_duplicado(self):
        self.procesar({"es_factura": False})
        otro = self.tmp / "o.pdf"
        otro.write_bytes(b"%PDF otro")
        self.assertEqual(self.procesar({"es_factura": False}, otro)["clave"], "")

    def test_todo_queda_guardado_con_su_detalle(self):
        f = self.procesar(respuesta(total=c(130.0)))
        guardada = self.db.obtener(f["id"])
        self.assertEqual(guardada["estado"], "revisar")
        self.assertEqual(json.loads(guardada["detalle"])["campos"]["total"]["valor"], 130.0)


class TestCuentas(BaseAlmacen):
    def nueva(self, n):
        f, d = self.otra_factura(n)
        return self.procesar(d, f)

    def test_proveedor_nuevo_va_a_revision_para_elegir_cuenta(self):
        f = self.nueva(1)
        self.assertEqual((f["estado"], f["cuenta_estado"], f["cuenta_contable"]), ("revisar", "nueva", ""))
        self.assertIn("Proveedor nuevo", f["a_revisar"])

    def test_se_propone_la_cuenta_como_dudosa_hasta_confirmarla_varias_veces(self):
        self.db.confirmar(self.nueva(1)["id"], "62900000")
        for veces in (1, 2):
            f = self.nueva(10 + veces)
            self.assertEqual((f["cuenta_contable"], f["cuenta_estado"], f["estado"]), ("62900000", "dudosa", "revisar"))
            self.assertIn(f"confirmada {veces} de 3", f["a_revisar"])
            self.db.confirmar(f["id"])
        f = self.nueva(20)  # ya confirmada 3 veces: se fía
        self.assertEqual((f["cuenta_contable"], f["cuenta_estado"], f["estado"]), ("62900000", "ok", "lista"))

    def test_si_el_gestor_cambia_la_cuenta_se_empieza_a_contar_de_nuevo(self):
        for n in (1, 2):
            self.db.confirmar(self.nueva(n)["id"], "62900000")
        self.assertEqual(self.db.cuenta_de("B12345674")["confirmaciones"], 2)
        self.db.confirmar(self.nueva(3)["id"], "60000000")
        c_ = self.db.cuenta_de("B12345674")
        self.assertEqual((c_["cuenta"], c_["confirmaciones"]), ("60000000", 1))

    def test_confirmar_dos_veces_la_misma_factura_cuenta_una(self):
        f = self.nueva(1)
        self.db.confirmar(f["id"], "62900000")
        self.db.confirmar(f["id"])
        self.assertEqual(self.db.cuenta_de("B12345674")["confirmaciones"], 1)

    def test_no_se_aprende_de_un_nif_invalido(self):
        self.assertEqual(self.db.aprender_cuenta("1234", "Fantasma", "62900000"), 0)
        self.assertIsNone(self.db.cuenta_de("1234"))

    def test_sin_cuenta_no_se_aprende_nada(self):
        self.db.confirmar(self.nueva(1)["id"])
        self.assertIsNone(self.db.cuenta_de("B12345674"))

    def test_confirmar_id_inexistente(self):
        with self.assertRaises(ValueError):
            self.db.confirmar(999)


class TestHoja(BaseAlmacen):
    def test_flujo_del_gestor_hoja_corregir_sincronizar_exportar(self):
        f = self.procesar(respuesta())
        hoja_csv, imp = self.tmp / "revision.csv", self.tmp / "imp.csv"
        self.assertEqual(hoja.escribir_hoja(self.db, hoja_csv), 1)

        # el gestor abre la hoja, pone cuenta y confirma
        with hoja_csv.open(newline="", encoding="utf-8-sig") as fh:
            filas = list(csv.DictReader(fh, delimiter=";"))
        filas[0].update(cuenta_contable="62900000", estado="confirmada", proveedor="Suministros Ficticios S.L. (corregido)")
        with hoja_csv.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=list(filas[0]), delimiter=";")
            w.writeheader(); w.writerows(filas)

        r = hoja.sincronizar(self.db, hoja_csv)
        self.assertEqual((r["modificadas"], r["confirmadas"]), (1, 1))
        guardada = self.db.obtener(f["id"])
        self.assertEqual((guardada["estado"], guardada["proveedor"]), ("confirmada", "Suministros Ficticios S.L. (corregido)"))
        self.assertEqual(self.db.cuenta_de("B12345674")["cuenta"], "62900000")  # aprendida al confirmar

        self.assertEqual(hoja.exportar(self.db, destino=imp), 1)
        self.assertEqual(imp.read_text(encoding="utf-8-sig").splitlines()[1],
                         "2026-10-15;2026-0042;B12345674;Suministros Ficticios S.L. (corregido);62900000;100,00;21,00;;121,00")

    def test_sincronizar_sin_cambios_no_toca_nada(self):
        self.procesar(respuesta())
        h = self.tmp / "r.csv"
        hoja.escribir_hoja(self.db, h)
        self.assertEqual(hoja.sincronizar(self.db, h), {"modificadas": 0, "confirmadas": 0, "ignoradas": []})

    def test_estado_inventado_en_la_hoja_se_ignora(self):
        self.procesar(respuesta())
        h = self.tmp / "r.csv"
        hoja.escribir_hoja(self.db, h)
        h.write_text(h.read_text(encoding="utf-8-sig").replace(";revisar;", ";aprobadisima;"), encoding="utf-8-sig")
        r = hoja.sincronizar(self.db, h)
        self.assertEqual(len(r["ignoradas"]), 1)
        self.assertEqual(self.db.listar()[0]["estado"], "revisar")

    def test_incluir_listas_y_lo_no_confirmado_no_se_exporta(self):
        self.procesar(respuesta())                       # revisar (proveedor nuevo)
        self.assertEqual(hoja.exportar(self.db, False, self.tmp / "a.csv"), 0)
        self.db.actualizar(1, estado="lista")
        self.assertEqual(hoja.exportar(self.db, True, self.tmp / "b.csv"), 1)
        self.assertEqual(hoja.exportar(self.db, False, self.tmp / "c.csv"), 0)


class TestVigilancia(BaseAlmacen):
    def test_procesa_lo_nuevo_una_sola_vez(self):
        carpeta = self.tmp / "entrada"
        carpeta.mkdir()
        (carpeta / "a.pdf").write_bytes(b"%PDF a")
        os.utime(carpeta / "a.pdf", (1, 1))  # antiguo: ya no se está copiando
        lector, vistos, avisos = Contador(respuesta()), {}, []
        prog = lambda i, n, r: avisos.append((i, n, r.name))
        self.assertEqual(len(pipeline.pasada_vigilancia(carpeta, self.db, lector, vistos, progreso=prog)), 1)
        self.assertEqual(pipeline.pasada_vigilancia(carpeta, self.db, lector, vistos), [])
        (carpeta / "b.pdf").write_bytes(b"%PDF b")
        os.utime(carpeta / "b.pdf", (1, 1))
        self.assertEqual(len(pipeline.pasada_vigilancia(carpeta, self.db, lector, vistos, progreso=prog)), 1)
        self.assertEqual(avisos, [(1, 1, "a.pdf"), (1, 1, "b.pdf")])

    def test_no_toca_un_archivo_que_aun_se_esta_copiando(self):
        carpeta = self.tmp / "entrada"
        carpeta.mkdir()
        (carpeta / "a.pdf").write_bytes(b"%PDF a")  # recién creado
        self.assertEqual(pipeline.pasada_vigilancia(carpeta, self.db, Falso(respuesta()), {}), [])


class TestNif(unittest.TestCase):
    def test_validos(self):
        for v in ("12345678Z", "00000000T", "X1234567L", "Y1234567X", "Z1234567R", "B12345674", "A58818501", "Q2826000H", "S2800568D", "P2807900B"):
            self.assertTrue(nif.validar(v)[0], v)

    def test_invalidos(self):
        for v in ("12345678A", "X1234567A", "B12345675", "Q2826000", "", "1234", "822334452"):
            self.assertFalse(nif.validar(v)[0], v)

    def test_normaliza_separadores(self):
        self.assertTrue(nif.validar("b-1234567.4")[0])

    def test_reparar_errores_tipicos_del_ocr(self):
        self.assertEqual(nif.reparar("822334452"), "B22334452")   # B leída como 8
        self.assertEqual(nif.reparar("1234S678Z"), "12345678Z")   # 5 leído como S
        self.assertIsNone(nif.reparar("B12345674"))                # ya es válido
        self.assertIsNone(nif.reparar("X1234567A"))                # ninguna corrección posible
        self.assertIsNone(nif.reparar("ABC"))

    def test_un_nif_corregido_nunca_queda_como_seguro(self):
        l = procesar.procesar_archivo(self_pdf(), Falso(respuesta(nif_proveedor=c("822334452"))))
        campo = l.campos["nif_proveedor"]
        self.assertEqual((campo.valor, campo.estado), ("B22334452", "dudoso"))
        self.assertIn("corregido", campo.motivo)
        self.assertEqual(l.estado, REVISAR)

    def test_nif_invalido_sin_arreglo_va_a_revision(self):
        l = procesar.procesar_archivo(self_pdf(), Falso(respuesta(nif_proveedor=c("B12345675"))))
        self.assertEqual((l.campos["nif_proveedor"].estado, l.estado), ("dudoso", REVISAR))


def self_pdf() -> Path:
    d = Path(tempfile.mkdtemp())
    (d / "f.pdf").write_bytes(b"%PDF-1.4 ficticio")
    return d / "f.pdf"


class TestRegresiones(unittest.TestCase):
    def test_fecha_iso_no_se_lee_como_dd_mm_aa(self):
        # Antes: "2026-10-05" se leía como 2005-10-26 y el lector la daba por segura.
        self.assertEqual(_fechas("Date: 2026-10-05"), ["2026-10-05"])
        self.assertEqual(_fechas("Fecha: 15/10/2026"), ["2026-10-15"])
        self.assertEqual(_fechas("tel 12-34-5678"), [])

    def test_ocr_lee_el_simbolo_numero_como_9(self):
        texto = "Taller S.L.\nNIF: B12345674 N9: TR-5512\nFecha: 08/10/2026\nFactura\nBase imponible 10,00\nIVA 21% 2,10\nTOTAL 12,10"
        self.assertEqual(extraer(texto)["campos"]["numero_factura"]["valor"], "TR-5512")

    def test_vat_cuenta_como_iva(self):
        texto = "Acme S.L.\nInvoice No: A-1\nDate: 2026-10-05\nSubtotal 100,00\nVAT 21% 21,00\nTOTAL 121,00"
        self.assertEqual(extraer(texto)["campos"]["cuota_iva"]["valor"], 21.0)


@unittest.skipUnless(HAY_TESSERACT, "falta tesseract")
class TestImagen(unittest.TestCase):
    def _texto(self, angulo=0, sombra=0.0):
        from PIL import Image, ImageDraw, ImageFont
        import numpy as np

        img = Image.new("L", (900, 1200), 250)
        d = ImageDraw.Draw(img)
        f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
        for i in range(24):
            d.text((60, 60 + i * 44), f"Linea de texto numero {i} con importe {i * 7},50", fill=20, font=f)
        img = img.rotate(angulo, expand=True, fillcolor=250, resample=Image.BICUBIC)
        if sombra:
            a = np.asarray(img, dtype="float32")
            xx = np.linspace(0, 1, a.shape[1])[None, :]
            img = Image.fromarray((a * (1 - sombra * xx)).astype("uint8"))
        return img

    def test_estima_el_giro(self):
        for real in (-8, -3, 4, 9):
            est = imagen.estimar_giro(self._texto(real))
            self.assertAlmostEqual(est, -real, delta=1.5, msg=f"giro real {real}")

    def test_una_pagina_recta_no_se_gira(self):
        self.assertEqual(imagen.estimar_giro(self._texto(0)), 0.0)

    def test_quitar_sombras_iguala_el_fondo(self):
        import numpy as np

        con = self._texto(0, sombra=0.6)
        sin = imagen.quitar_sombras(con)
        fondo = lambda im: np.asarray(im, dtype="float32")[:30, :]  # franja de papel sin texto
        self.assertGreater(fondo(sin).mean(), fondo(con).mean() + 20)
        self.assertLess(fondo(sin).std(), 12)


@unittest.skipUnless(HAY_PDFTOTEXT and HAY_TESSERACT, "falta pdftotext o tesseract")
class TestJuegoDeFacturas(unittest.TestCase):
    """Lee las 21 facturas variadas y exige 0 errores marcados como seguros y un acierto mínimo."""

    def test_sin_errores_marcados_como_seguros(self):
        d = Path(tempfile.mkdtemp())
        lecturas = procesar.procesar_carpeta(VARIADOS, LectorLocal())
        self.assertEqual(len(lecturas), 21)  # entran 21, salen 21
        (d / "r.json").write_text(json.dumps([l.a_dict() for l in lecturas]))
        with mock.patch("builtins.print") as p:
            comparar.main([str(VARIADOS / "esperado.json"), str(d / "r.json")])
        salida = "\n".join(str(a.args[0]) for a in p.call_args_list if a.args)
        self.assertIn("ERRORES MARCADOS COMO SEGUROS: 0", salida)
        porcentaje = int(salida.split("TOTAL")[1].split("(")[1].split("%")[0])
        self.assertGreaterEqual(porcentaje, 90, salida)


class TestIngesta(unittest.TestCase):
    def test_guarda_pdf_por_remitente_y_sanea_el_nombre(self):
        m = EmailMessage()
        m["From"] = "Cliente Uno <cliente@ejemplo.com>"
        m.set_content("Adjunto factura")
        m.add_attachment(b"%PDF", maintype="application", subtype="pdf", filename="../../etc/pasa wd.pdf")
        m.add_attachment(b"x", maintype="application", subtype="zip", filename="malware.zip")
        with tempfile.TemporaryDirectory() as d:
            guardados = ingesta.guardar_adjuntos(m, Path(d))
            self.assertEqual(len(guardados), 1)  # el zip se ignora
            ruta, remitente = guardados[0]
            self.assertEqual(remitente, "cliente@ejemplo.com")
            self.assertTrue(ruta.resolve().is_relative_to(Path(d).resolve()))

    def test_sin_credenciales(self):
        with mock.patch.object(config, "IMAP_USER", ""):
            with self.assertRaises(RuntimeError):
                ingesta.descargar_nuevos()


class TestComparar(unittest.TestCase):
    def _comparar(self, esperado, leido):
        d = Path(tempfile.mkdtemp())
        (d / "e.json").write_text(json.dumps(esperado))
        (d / "r.json").write_text(json.dumps(leido))
        with mock.patch("builtins.print") as p:
            comparar.main([str(d / "e.json"), str(d / "r.json")])
        return "\n".join(str(a.args[0]) for a in p.call_args_list if a.args)

    def test_error_dado_por_bueno_se_cuenta_como_peligroso(self):
        leido = [{"archivo": "a.pdf", "estado": "lista", "error": "",
                  "campos": {"total": {"valor": 120.0, "estado": "ok", "motivo": ""}}}]
        salida = self._comparar({"a.pdf": {"total": 121.0}}, leido)
        self.assertIn("ERRORES MARCADOS COMO SEGUROS: 1", salida)

    def test_error_marcado_dudoso_no_es_peligroso(self):
        leido = [{"archivo": "a.pdf", "estado": "revisar", "error": "",
                  "campos": {"total": {"valor": 120.0, "estado": "dudoso", "motivo": ""}}}]
        self.assertIn("ERRORES MARCADOS COMO SEGUROS: 0", self._comparar({"a.pdf": {"total": 121.0}}, leido))


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for nombre, valor in (("BASE_DATOS", "f.db"), ("REVISION", "r.csv"), ("IMPORTACION", "i.csv")):
            p = mock.patch.object(config, nombre, self.tmp / valor)
            p.start(); self.addCleanup(p.stop)
        p = mock.patch("builtins.print"); self.print = p.start(); self.addCleanup(p.stop)

    def test_procesar_confirmar_hoja_y_exportar(self):
        self.assertEqual(cli.main(["procesar", str(EJEMPLOS), "--lector", "simulado"]), 0)
        db = Almacen()
        estados = {Path(f["archivo"]).name: f["estado"] for f in db.listar()}
        db.cerrar()
        self.assertEqual(estados, {"factura_dudosa.pdf": "revisar", "factura_ok.pdf": "revisar",  # proveedor nuevo: falta cuenta
                                   "factura_texto.pdf": "error", "menu_restaurante.pdf": "error"})
        self.assertEqual(cli.main(["confirmar", "2", "--cuenta", "62900000"]), 0)
        self.assertEqual(cli.main(["cuentas"]), 0)
        self.assertEqual(cli.main(["hoja"]), 0)
        self.assertEqual(cli.main(["exportar"]), 0)
        self.assertEqual(len((self.tmp / "i.csv").read_text(encoding="utf-8-sig").splitlines()), 2)

    def test_la_segunda_pasada_no_vuelve_a_leer(self):
        cli.main(["procesar", str(EJEMPLOS / "factura_ok.pdf"), "--lector", "simulado"])
        cli.main(["procesar", str(EJEMPLOS / "factura_ok.pdf"), "--lector", "simulado"])
        db = Almacen()
        self.assertEqual([f["estado"] for f in db.listar()], ["revisar", "repetida"])
        db.cerrar()

    def test_confirmar_un_id_inexistente_da_error_claro(self):
        with mock.patch("sys.stderr"):
            self.assertEqual(cli.main(["confirmar", "999"]), 2)

    def test_falta_la_clave_da_un_error_claro(self):
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": ""}), mock.patch("sys.stderr"):
            self.assertEqual(cli.main(["procesar", str(PDF_TEXTO), "--lector", "gemini"]), 2)


if __name__ == "__main__":
    unittest.main()
