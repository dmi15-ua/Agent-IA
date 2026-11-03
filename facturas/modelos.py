"""Campos compartidos entre extracción, validación y hoja de revisión."""

# Lo que el modelo de visión rellena.
CAMPOS_MODELO = (
    "proveedor",
    "nif_proveedor",
    "numero_factura",
    "fecha",
    "base_imponible",
    "tipo_iva",
    "cuota_iva",
    "total",
    "confianza",
    "notas",
)

# Estados de una fila en la hoja de revisión.
LISTA = "lista"            # pasó todas las validaciones
REVISAR = "revisar"        # el gestor debe mirarla
REPETIDA = "repetida"      # misma clave que otra ya procesada; no se exporta
CONFIRMADA = "confirmada"  # el gestor la dio por buena (se pone a mano en la hoja)

# Columnas de la hoja de revisión (revision.csv), en este orden.
COLUMNAS_REVISION = (
    "recibida",
    "remitente",
    "archivo",
    "estado",
    "motivos",
    *CAMPOS_MODELO,
    "clave",
)
