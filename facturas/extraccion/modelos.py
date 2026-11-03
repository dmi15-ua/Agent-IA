"""Datos que produce la lectura. Lo que se le pasa a la otra pieza.

Cada campo lleva su propio estado:
  ok         leído con claridad y pasa las comprobaciones
  dudoso     se leyó, pero hay algo raro
  no_leido   no se pudo leer: el valor queda vacío, nunca inventado

Cada factura termina en uno de tres estados:
  lista      todos los campos ok
  revisar    algún campo dudoso o no_leido: una persona la mira siempre
  error      no se pudo procesar: se avisa con un motivo y qué hacer
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

OK, DUDOSO, NO_LEIDO = "ok", "dudoso", "no_leido"
LISTA, REVISAR, ERROR = "lista", "revisar", "error"

CAMPOS_TEXTO = (
    "numero_factura", "fecha_expedicion", "proveedor", "nif_proveedor",
    "cliente", "nif_cliente", "descripcion", "moneda",
)
CAMPOS_NUMERO = ("base_imponible", "cuota_iva", "total", "retencion_irpf")
TODOS_LOS_CAMPOS = CAMPOS_TEXTO + CAMPOS_NUMERO
# Si falta uno de estos, la factura no puede darse por buena.
OBLIGATORIOS = (
    "numero_factura", "fecha_expedicion", "proveedor", "nif_proveedor",
    "cliente", "nif_cliente", "base_imponible", "cuota_iva", "total",
)


@dataclass
class Campo:
    valor: Any = None
    estado: str = NO_LEIDO
    motivo: str = ""

    def avisar(self, motivo: str) -> None:
        """Añade un motivo. Un campo ok pasa a dudoso; uno no_leido sigue como no_leido."""
        if self.estado == OK:
            self.estado = DUDOSO
        self.motivo = f"{self.motivo}; {motivo}" if self.motivo else motivo


@dataclass
class Lectura:
    archivo: str
    estado: str = REVISAR
    campos: dict[str, Campo] = field(default_factory=dict)
    desglose_iva: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""
    que_hacer: str = ""

    def campos_a_revisar(self) -> list[str]:
        return [n for n, c in self.campos.items() if c.estado != OK]

    def a_dict(self) -> dict[str, Any]:
        return {
            "archivo": self.archivo,
            "estado": self.estado,
            "error": self.error,
            "que_hacer": self.que_hacer,
            "campos": {
                n: {"valor": c.valor, "estado": c.estado, "motivo": c.motivo}
                for n, c in self.campos.items()
            },
            "desglose_iva": self.desglose_iva,
        }
