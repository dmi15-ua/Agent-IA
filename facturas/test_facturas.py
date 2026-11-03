"""Tests del agente de facturas. Sin red ni API key.

    python -m unittest facturas.test_facturas -v
"""
import json
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path
from unittest import mock

from . import config, extraccion, hoja, ingesta, pipeline, validacion

OK = {
    "proveedor": "Suministros Ficticios S.L.",
    "nif_proveedor": "B12345674",
    "numero_factura": "2026-0042",
    "fecha": "2026-10-15",
    "base_imponible": 100.00,
    "tipo_iva": 21,
    "cuota_iva": 21.00,
    "total": 121.00,
    "confianza": "alta",
    "notas": "",
}


class TestImportes(unittest.TestCase):
    def test_formatos(self):
        casos = {1234.56: 123456, "1234.56": 123456, "1.234,56": 123456, "1,234.56": 123456,
                 "12,5 €": 1250, "0.1": 10, None: None, "": None, "abc": None}
        for entrada, esperado in casos.items():
            self.assertEqual(validacion.a_centimos(entrada), esperado, entrada)

    def test_sin_errores_de_coma_flotante(self):
        self.assertEqual(validacion.a_centimos(0.1) + validacion.a_centimos(0.2), validacion.a_centimos(0.3))


class TestValidacion(unittest.TestCase):
    def test_factura_correcta(self):
        r = validacion.validar(OK)
        self.assertEqual((r["estado"], r["motivos"]), ("lista", ""))
        self.assertEqual(r["clave"], "B12345674|2026-0042|12100")

    def test_no_cuadra(self):
        r = validacion.validar({**OK, "total": 130.00})
        self.assertEqual(r["estado"], "revisar")
        self.assertIn("no suma el total", r["motivos"])

    def test_nif_dudoso_y_normalizado(self):
        self.assertIn("NIF", validacion.validar({**OK, "nif_proveedor": "1234"})["motivos"])
        self.assertEqual(validacion.validar({**OK, "nif_proveedor": "b-1234567.4"})["estado"], "lista")

    def test_campos_vacios_y_confianza(self):
        r = validacion.validar({**OK, "proveedor": "", "confianza": "baja"})
        self.assertIn("Faltan campos: proveedor", r["motivos"])
        self.assertIn("Confianza", r["motivos"])

    def test_notas_del_modelo_fuerzan_revision(self):
        self.assertEqual(validacion.validar({**OK, "notas": "foto torcida"})["estado"], "revisar")

    def test_cuota_incoherente_con_el_tipo(self):
        # suma bien (100+10=110) pero 10 no es el 21% de 100
        r = validacion.validar({**OK, "cuota_iva": 10.00, "total": 110.00})
        self.assertIn("base × tipo", r["motivos"])

    def test_fecha_futura_e_invalida(self):
        self.assertIn("futuro", validacion.validar({**OK, "fecha": "2999-01-01"})["motivos"])
        self.assertIn("Fecha no válida", validacion.validar({**OK, "fecha": "15/10/2026"})["motivos"])

    def test_sin_clave_si_faltan_datos_de_identidad(self):
        self.assertEqual(validacion.validar({**OK, "numero_factura": ""})["clave"], "")

    def test_respuesta_vacia_no_rompe(self):
        r = validacion.validar({})
        self.assertEqual(r["estado"], "revisar")


class TestParseo(unittest.TestCase):
    def test_json_en_bloque_de_codigo(self):
        d = extraccion.parsear_respuesta("```json\n" + json.dumps(OK) + "\n```")
        self.assertEqual(d["total"], 121.0)

    def test_sin_json(self):
        with self.assertRaises(extraccion.ErrorExtraccion):
            extraccion.parsear_respuesta("Lo siento, no puedo")

    def test_solo_campos_esperados(self):
        self.assertNotIn("extra", extraccion.parsear_respuesta(json.dumps({**OK, "extra": 1})))


class TestFlujo(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.hoja = self.tmp / "revision.csv"
        self.pdf = self.tmp / "f.pdf"
        self.pdf.write_bytes(b"%PDF-1.4 ficticio")

    def _sidecar(self, datos):
        (self.tmp / "f.pdf.json").write_text(json.dumps(datos))

    def test_de_principio_a_fin_con_duplicado_y_exportacion(self):
        self._sidecar(OK)
        a = pipeline.procesar_archivo(self.pdf, "prov@x.com", "simulado", self.hoja)
        b = pipeline.procesar_archivo(self.pdf, "prov@x.com", "simulado", self.hoja)
        self.assertEqual((a["estado"], b["estado"]), ("lista", "repetida"))

        # Sin confirmar nada no se exporta nada
        dest = self.tmp / "imp.csv"
        self.assertEqual(hoja.exportar(ruta_hoja=self.hoja, destino=dest), 0)

        # El gestor confirma la primera editando la hoja
        filas = hoja.leer(self.hoja)
        filas[0]["estado"] = "confirmada"
        hoja._escribir(filas, self.hoja)
        self.assertEqual(hoja.exportar(ruta_hoja=self.hoja, destino=dest), 1)
        lineas = dest.read_text(encoding="utf-8-sig").splitlines()
        self.assertEqual(lineas[1], "2026-10-15;2026-0042;B12345674;Suministros Ficticios S.L.;100,00;21;21,00;121,00")

    def test_incluir_listas(self):
        self._sidecar(OK)
        pipeline.procesar_archivo(self.pdf, "", "simulado", self.hoja)
        self.assertEqual(hoja.exportar(True, self.hoja, self.tmp / "i.csv"), 1)

    def test_fallo_de_lectura_no_se_pierde(self):
        r = pipeline.procesar_archivo(self.pdf, "p@x.com", "simulado", self.hoja)  # sin .json
        self.assertEqual(r["estado"], "revisar")
        self.assertIn("No se pudo leer", r["motivos"])
        self.assertEqual(len(hoja.leer(self.hoja)), 1)

    def test_los_importes_dudosos_no_se_inventan(self):
        self._sidecar({**OK, "base_imponible": None, "cuota_iva": None})
        r = pipeline.procesar_archivo(self.pdf, "", "simulado", self.hoja)
        self.assertEqual((r["base_imponible"], r["estado"]), ("", "revisar"))


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
            self.assertEqual(ruta.parent.name, "cliente@ejemplo.com")


class TestApis(unittest.TestCase):
    def test_gemini_sin_clave(self):
        with mock.patch.object(config, "GEMINI_API_KEY", ""):
            with self.assertRaises(extraccion.ErrorExtraccion):
                extraccion.extraer_gemini(Path("x.pdf"))

    def test_claude_parsea_respuesta(self):
        tmp = Path(tempfile.mkdtemp()) / "f.pdf"
        tmp.write_bytes(b"%PDF")
        resp = mock.Mock(status_code=200)
        resp.json.return_value = {"content": [{"type": "text", "text": json.dumps(OK)}]}
        with mock.patch.object(config, "ANTHROPIC_API_KEY", "k"), mock.patch("httpx.post", return_value=resp) as post:
            d = extraccion.extraer_claude(tmp)
        self.assertEqual(d["numero_factura"], "2026-0042")
        self.assertEqual(post.call_args.kwargs["json"]["messages"][0]["content"][0]["type"], "document")

    def test_error_http(self):
        tmp = Path(tempfile.mkdtemp()) / "f.png"
        tmp.write_bytes(b"x")
        resp = mock.Mock(status_code=429, text="cuota")
        with mock.patch.object(config, "GEMINI_API_KEY", "k"), mock.patch("httpx.post", return_value=resp):
            with self.assertRaises(extraccion.ErrorExtraccion):
                extraccion.extraer_gemini(tmp)


if __name__ == "__main__":
    unittest.main()
