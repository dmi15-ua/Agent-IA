"""Lector sin IA ni cuentas: saca el texto del PDF o de la foto y aplica reglas.

  PDF con texto  -> pdftotext (exacto)
  PDF escaneado  -> pdftoppm + OCR
  Foto / imagen  -> OCR con Tesseract

Necesita programas instalados en el sistema (no se instalan con pip):
  Ubuntu/Debian:  sudo apt install tesseract-ocr tesseract-ocr-spa poppler-utils
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from .reglas_texto import extraer

PAGINAS_MAXIMAS = 3
CALIDAD_ILEGIBLE = 30  # por debajo, el OCR no ha entendido casi nada: se avisa como error
AYUDA_INSTALACION = "Instala los programas: sudo apt install tesseract-ocr tesseract-ocr-spa poppler-utils"


class LectorNoDisponible(Exception):
    que_hacer = AYUDA_INSTALACION


class LecturaIlegible(Exception):
    que_hacer = "Pide al cliente una foto más nítida (recta, con buena luz y sin sombras) o el PDF original."


class LectorLocal:
    def leer(self, ruta: Path, instruccion: str) -> str:  # instruccion no se usa: no hay modelo
        texto, calidad = self._texto(ruta)
        return json.dumps(extraer(texto, calidad), ensure_ascii=False)

    # ------------------------------------------------------------ obtener el texto

    def _texto(self, ruta: Path) -> tuple[str, Optional[float]]:
        if ruta.suffix.lower() == ".pdf":
            texto = self._pdf_con_texto(ruta)
            if len(texto.strip()) >= 40:
                return texto, None  # texto digital: sin errores de OCR
            return self._ocr_pdf(ruta)
        return self._ocr_imagen(ruta)

    @staticmethod
    def _requiere(programa: str) -> None:
        if shutil.which(programa) is None:
            raise LectorNoDisponible(f"Falta el programa '{programa}'.")

    def _pdf_con_texto(self, ruta: Path) -> str:
        self._requiere("pdftotext")
        r = subprocess.run(["pdftotext", "-layout", "-l", str(PAGINAS_MAXIMAS), str(ruta), "-"],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise LecturaIlegible(f"El PDF no se puede abrir ({r.stderr.strip() or 'archivo dañado o con contraseña'}).")
        return r.stdout

    def _ocr_pdf(self, ruta: Path) -> tuple[str, Optional[float]]:
        self._requiere("pdftoppm")
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run(["pdftoppm", "-r", "200", "-png", "-l", str(PAGINAS_MAXIMAS), str(ruta), f"{tmp}/p"],
                               capture_output=True, text=True, timeout=120)
            paginas = sorted(Path(tmp).glob("p*.png"))
            if r.returncode != 0 or not paginas:
                raise LecturaIlegible("El PDF no se puede convertir a imagen (dañado o con contraseña).")
            partes = [self._ocr_imagen(p) for p in paginas]
        return "\n".join(t for t, _ in partes), min(c for _, c in partes if c is not None)

    def _ocr_imagen(self, ruta: Path) -> tuple[str, float]:
        self._requiere("tesseract")
        try:
            import pytesseract
            from PIL import Image, ImageOps
        except ImportError as e:
            raise LectorNoDisponible("Faltan librerías de Python: pip install pytesseract Pillow") from e

        try:
            with Image.open(ruta) as original:
                gris = ImageOps.exif_transpose(original).convert("L")  # gira las fotos del móvil
        except Exception as e:
            raise LecturaIlegible(f"La imagen no se puede abrir ({type(e).__name__}).") from e

        idioma = "spa" if "spa" in pytesseract.get_languages(config="") else "eng"
        candidatas = [self._preparar(gris)]  # el tratamiento sencillo de siempre
        try:
            from .imagen import mejorar  # enderezar y quitar sombras; necesita numpy

            candidatas.append(self._preparar(mejorar(gris)))
        except ImportError:
            pass
        # Se queda con la variante en la que el OCR reconoce más palabras con confianza.
        resultados = [self._reconocer(c, idioma, pytesseract) for c in candidatas]
        texto, calidad, buenas = max(resultados, key=lambda r: r[2])
        if buenas == 0:
            raise LecturaIlegible("No se ha podido leer ningún texto en la imagen.")
        if calidad < CALIDAD_ILEGIBLE:
            raise LecturaIlegible(f"La imagen se lee con muy poca calidad ({calidad:.0f} %).")
        return texto, calidad

    @staticmethod
    def _preparar(gris):
        from PIL import ImageOps

        imagen = ImageOps.autocontrast(gris)
        if imagen.width < 1600:  # el OCR rinde mejor con letras grandes
            imagen = imagen.resize((1600, round(imagen.height * 1600 / imagen.width)))
        return imagen

    @staticmethod
    def _reconocer(imagen, idioma, pytesseract) -> tuple[str, float, int]:
        """(texto, calidad media 0-100, nº de palabras reconocidas con confianza >= 60)."""
        datos = pytesseract.image_to_data(imagen, lang=idioma, config="--psm 4", output_type=pytesseract.Output.DICT)
        palabras = [float(c) for t, c in zip(datos["text"], datos["conf"]) if t.strip() and float(c) >= 0]
        if not palabras:
            return "", 0.0, 0
        texto = pytesseract.image_to_string(imagen, lang=idioma, config="--psm 4")
        return texto, sum(palabras) / len(palabras), sum(1 for c in palabras if c >= 60)
