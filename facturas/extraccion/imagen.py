"""Mejora de fotos de móvil antes del OCR: quitar sombras y enderezar.

Necesita numpy (pip install numpy). Sin numpy no se mejora nada y el lector sigue funcionando.
"""
import numpy as np
from PIL import Image, ImageFilter, ImageOps

GIRO_MAXIMO = 20.0  # grados a cada lado que se buscan


def quitar_sombras(gris: Image.Image) -> Image.Image:
    """Divide la imagen por su fondo estimado: el papel queda blanco aunque tenga sombra o poca luz.

    El fondo se estima con un filtro de máximo sobre una copia pequeña (el texto, fino, desaparece
    y queda solo el papel iluminado) y se suaviza. Se trabaja a 1/6 de escala por velocidad.
    """
    ancho, alto = gris.size
    pequena = gris.resize((max(ancho // 6, 1), max(alto // 6, 1)), Image.BILINEAR)
    fondo = pequena.filter(ImageFilter.MaxFilter(15)).filter(ImageFilter.GaussianBlur(6))
    fondo = np.asarray(fondo.resize((ancho, alto), Image.BICUBIC), dtype="float32")
    a = np.asarray(gris, dtype="float32") / np.maximum(fondo, 1.0) * 255.0
    return Image.fromarray(np.clip(a, 0, 255).astype("uint8"))


def estimar_giro(gris: Image.Image) -> float:
    """Ángulo (grados, sentido antihorario de Pillow) que hay que girar la imagen para dejar el texto horizontal.

    Se prueba cada ángulo sobre una copia pequeña en blanco y negro: el correcto es el que concentra
    los píxeles de texto en filas bien separadas (perfil de proyección de máxima varianza).
    """
    copia = gris.copy()
    copia.thumbnail((700, 700))
    a = np.asarray(copia, dtype="float32")
    texto = Image.fromarray(((a < a.mean() - 0.6 * a.std()) * 255).astype("uint8"))

    def puntuacion(grados: float) -> float:
        filas = np.asarray(texto.rotate(grados, resample=Image.NEAREST), dtype="float32").sum(axis=1)
        return float(filas.var())

    grueso = max(np.arange(-GIRO_MAXIMO, GIRO_MAXIMO + 0.1, 1.0), key=puntuacion)
    fino = max(np.arange(grueso - 1, grueso + 1.01, 0.2), key=puntuacion)
    return 0.0 if puntuacion(fino) <= puntuacion(0.0) * 1.02 else float(fino)  # sin mejora clara: no tocar


def mejorar(gris: Image.Image) -> Image.Image:
    """Sombras fuera, texto horizontal y contraste máximo."""
    limpia = quitar_sombras(gris)
    giro = estimar_giro(limpia)
    if giro:
        limpia = limpia.rotate(giro, expand=True, resample=Image.BICUBIC, fillcolor=255)
    return ImageOps.autocontrast(limpia, cutoff=1)
