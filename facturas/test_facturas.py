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

from . import __main__ as cli
from . import comparar, config, hoja, ingesta, pipeline
from .extraccion import procesar, proveedor
from .extraccion.lector_local import LectorLocal
from .extraccion.modelos import ERROR, LISTA, REVISAR
from .extraccion.reglas_texto import extraer

EJEMPLOS = Path(__file__).parent / "ejemplos"
PDF_TEXTO = EJEMPLOS / "factura_texto.pdf"
HAY_PDFTOTEXT = shutil.which("pdftotext") is not None


def c(valor, legible="claro", motivo=""):
    return {"valor": valor, "legible": legible, "motivo": motivo}


def respuesta(**cambios) -> dict:
    campos = {
        "numero_factura": c("2026-0042"), "fecha_expedicion": c("2026-10-15"),
        "proveedor": c("Suministros Ficticios S.L."), "nif_proveedor": c("B12345674"),
        "cliente": c("Cliente Demo S.L."), "nif_cliente": c("B87654321"),
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


class TestHoja(Base):
    def test_duplicados_y_exportacion(self):
        a = pipeline.procesar_archivo(self.pdf, "p@x.com", Falso(respuesta()), self.hoja)
        b = pipeline.procesar_archivo(self.pdf, "p@x.com", Falso(respuesta()), self.hoja)
        self.assertEqual((a["estado"], b["estado"]), ("lista", "repetida"))
        self.assertEqual(a["clave"], "B12345674|2026-0042|12100")

        dest = self.tmp / "imp.csv"
        self.assertEqual(hoja.exportar(ruta_hoja=self.hoja, destino=dest), 0)  # nada confirmado

        filas = hoja.leer(self.hoja)
        filas[0]["estado"] = "confirmada"  # el gestor edita la hoja
        hoja.escribir(filas, self.hoja)
        self.assertEqual(hoja.exportar(ruta_hoja=self.hoja, destino=dest), 1)
        self.assertEqual(dest.read_text(encoding="utf-8-sig").splitlines()[1],
                         "2026-10-15;2026-0042;B12345674;Suministros Ficticios S.L.;100,00;21,00;;121,00")

    def test_incluir_listas(self):
        pipeline.procesar_archivo(self.pdf, "", Falso(respuesta()), self.hoja)
        self.assertEqual(hoja.exportar(True, self.hoja, self.tmp / "i.csv"), 1)

    def test_error_y_revisar_no_se_pierden_ni_se_exportan(self):
        pipeline.procesar_archivo(self.pdf, "", Falso({"es_factura": False}), self.hoja)
        pipeline.procesar_archivo(self.pdf, "", Falso(respuesta(total=c(1.0))), self.hoja)
        filas = hoja.leer(self.hoja)
        self.assertEqual([f["estado"] for f in filas], ["error", "revisar"])
        self.assertEqual(filas[0]["clave"], "")  # un error nunca cuenta como duplicado
        self.assertEqual(hoja.exportar(True, self.hoja, self.tmp / "i.csv"), 0)

    def test_misma_factura_con_importe_distinto_no_es_duplicado(self):
        pipeline.procesar_archivo(self.pdf, "", Falso(respuesta()), self.hoja)
        otra = respuesta(total=c(106.0), retencion_irpf=c(15.0))
        self.assertEqual(pipeline.procesar_archivo(self.pdf, "", Falso(otra), self.hoja)["estado"], "lista")


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
    def test_procesar_simulado_de_una_carpeta_y_exportar(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        with mock.patch.object(config, "REVISION", tmp / "r.csv"), mock.patch.object(config, "IMPORTACION", tmp / "i.csv"), \
                mock.patch("builtins.print"):
            self.assertEqual(cli.main(["procesar", str(EJEMPLOS), "--lector", "simulado"]), 0)
            estados = {Path(f["archivo"]).name: f["estado"] for f in hoja.leer()}
            self.assertEqual(estados, {"factura_dudosa.pdf": "revisar", "factura_ok.pdf": "lista",
                                       "factura_texto.pdf": "error", "menu_restaurante.pdf": "error"})
            self.assertEqual(cli.main(["exportar", "--incluir-listas"]), 0)
            self.assertEqual(len((tmp / "i.csv").read_text(encoding="utf-8-sig").splitlines()), 2)

    def test_falta_la_clave_da_un_error_claro(self):
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": ""}), mock.patch("sys.stderr"):
            self.assertEqual(cli.main(["procesar", str(PDF_TEXTO), "--lector", "gemini"]), 2)


if __name__ == "__main__":
    unittest.main()
