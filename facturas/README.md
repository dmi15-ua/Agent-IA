# Agente de facturas

```
Correo (IMAP) → adjunto guardado por remitente → modelo de visión (lee)
→ validaciones por código → duplicados → revision.csv → importacion.csv
```

La IA **solo lee** la factura. Todo lo que decide si es fiable (suma, NIF, IVA, fecha,
duplicados) son reglas fijas en `validacion.py`.

## Probarlo sin API ni coste

```bash
python -m facturas procesar facturas/ejemplos/factura_ok.pdf facturas/ejemplos/factura_dudosa.pdf \
    --remitente cliente@ejemplo.com --extractor simulado
python -m unittest facturas.test_facturas -v
```

El modo `simulado` lee `<factura>.json` en lugar de llamar a un modelo.

## Con una factura real

```bash
# en .env: GEMINI_API_KEY=...   (o FACTURAS_EXTRACTOR=claude + ANTHROPIC_API_KEY=...)
python -m facturas procesar mi_factura.pdf --remitente cliente@ejemplo.com
python -m facturas correo        # baja los adjuntos de correos NO leídos y los procesa
```

## Revisión y exportación

1. Se abre `facturas_datos/revision.csv` (delimitador `;`) en Excel o Google Sheets.
2. Se filtra por `estado = revisar`, se corrige y se cambia a `confirmada`.
3. `python -m facturas exportar` genera `facturas_datos/importacion.csv` solo con las confirmadas
   (`--incluir-listas` añade las que pasaron todas las validaciones sin revisión humana).

Estados: `lista` · `revisar` · `repetida` (misma clave NIF|nº|total, no se exporta) · `confirmada`.

Las columnas del CSV de importación están en `hoja.COLUMNAS_IMPORTACION`; hay que
adaptarlas al formato que pida el programa de contabilidad.

## Reglas de validación

Base + IVA = total (en céntimos) · cuota ≈ base × tipo (±2 cts) · tipo de IVA 0/4/10/21 ·
formato de NIF/CIF/NIE · campos obligatorios · fecha válida y no futura · total > 0 ·
confianza `alta` y sin notas del modelo. Cualquier fallo → `revisar`.
Solo se comprueba el **formato** del NIF, no la letra de control ni que exista.

## Antes de usar facturas reales

- La carpeta `facturas_datos/` está en `.gitignore`: no la subáis nunca al repositorio.
- Con la API, las facturas salen a un tercero: contrato de tratamiento de datos y revisar
  la retención del proveedor del modelo antes de procesar facturas de clientes.
- Fijad un límite de gasto en la cuenta de la API.
- El buzón debe ser dedicado, con contraseña de aplicación.
