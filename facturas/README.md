# Agente de facturas

Lee facturas (PDF o foto), marca **cada campo** como `ok`, `dudoso` o `no_leido`, comprueba lo
que se puede comprobar con código, detecta repetidas y deja todo en una hoja que revisa el
gestor. De ahí sale el CSV para el programa de contabilidad.

```
Correo (IMAP) → adjunto guardado por remitente → LECTOR → comprobaciones del código
→ duplicados → revision.csv (el gestor confirma) → importacion.csv
```

**Reglas de oro:** el modelo propone y el código comprueba (una comprobación solo puede empeorar
un campo); lo que no se lee queda vacío, nunca se inventa; toda factura que entra termina en
`lista`, `revisar` o `error` (si entran N, salen N).

## Los lectores (`--lector` o `FACTURAS_LECTOR`)

| Lector | Qué hace | Coste | La factura… |
| --- | --- | --- | --- |
| `local` (por defecto) | OCR + reglas fijas. Busca etiquetas como "Base imponible"; no entiende la factura | Gratis | no sale del equipo |
| `ollama` | IA que corre en vuestro ordenador lee el texto (`ollama pull qwen2.5:7b`) | Gratis | no sale del equipo |
| `gemini` | Modelo con visión por API (`GEMINI_API_KEY`) | De pago, por uso | **se envía a Google** |
| `claude` | Modelo con visión por API (`ANTHROPIC_API_KEY`, `pip install anthropic`) | De pago, por uso | **se envía a Anthropic** |
| `simulado` | Devuelve las respuestas escritas a mano en `<factura>.respuesta.json`. Solo para probar | Gratis | — |

**Verificación contra el texto.** `gemini` y `claude` van envueltos en una comprobación: si el PDF
tiene texto digital, cada dato que el modelo da por claro se busca en ese texto. Lo que no aparece
baja a `dudoso`. `ollama` hace lo mismo también con fotos (usa el OCR). Con fotos y `gemini`/`claude`
no hay verificación (haría falta OCR).

## Probarlo sin cuentas ni coste

```bash
python -m unittest facturas.test_facturas -v

# PDF con texto, leído de verdad con el lector local (necesita poppler-utils)
python -m facturas procesar facturas/ejemplos/factura_texto.pdf --remitente cliente@ejemplo.com

# Respuestas escritas a mano: una buena, una dudosa y un documento que no es factura
python -m facturas procesar facturas/ejemplos --lector simulado
```

Para fotos y PDF escaneados con `local`: `sudo apt install tesseract-ocr tesseract-ocr-spa poppler-utils`
y `pip install -r facturas/requirements.txt`.

## Uso real

```bash
python -m facturas procesar mi_factura.pdf otra_carpeta/ --remitente cliente@ejemplo.com
python -m facturas correo           # baja los adjuntos de correos NO leídos y los procesa
python -m facturas exportar         # CSV de importación con las confirmadas
```

### Revisión y exportación

1. Se abre `facturas_datos/revision.csv` (delimitador `;`) en Excel o Google Sheets.
2. Se filtra por `estado = revisar`; la columna `a_revisar` dice qué campos y por qué.
3. Se corrige y se cambia el estado a `confirmada`.
4. `python -m facturas exportar` genera `facturas_datos/importacion.csv` solo con las confirmadas
   (`--incluir-listas` añade las `lista` sin revisión humana).

Estados: `lista` · `revisar` · `error` (mirad `error` y `que_hacer`) · `repetida` (misma clave
NIF|número|total; no se exporta) · `confirmada`.
Las columnas del CSV de importación están en `hoja.COLUMNAS_IMPORTACION`: adaptadlas al programa
de contabilidad.

## Medir si acierta

1. Escribid a mano los valores correctos en un `esperado.json` junto a las facturas
   (modelo: `ejemplos/esperado.json`; solo hace falta poner los campos que queráis comprobar).
2. ```bash
   python -m facturas leer tu_carpeta --lector ollama --salida resultados
   python -m facturas comparar tu_carpeta/esperado.json resultados/resultado.json
   ```
3. La cifra clave es **errores marcados como seguros**: un campo mal leído que se dio por `ok`
   y se colaría sin revisión. **Debe ser 0.** Si no lo es, es lo primero que hay que arreglar.
   Probad varios lectores y modelos con las mismas facturas y comparad.

## Comprobaciones del código

Campos obligatorios · formato de NIF/CIF/NIE (solo el formato, no la letra de control ni que exista) ·
fecha válida y no futura · moneda EUR · base + IVA = total (acepta también el caso con retención de
IRPF; tolerancia 2 céntimos) · desglose de IVA coherente (cuota = base × tipo, suma = totales) ·
tipos de IVA 0, 4, 5, 10 y 21 % (no cubre IGIC de Canarias: revisadlo con un asesor).

## Lo que se sabe que falla o falta

- Probado solo con facturas ficticias. Con reales de otros diseños aparecerán fallos nuevos: es el objetivo de medir.
- `local`: no entiende la factura; las de autónomos (nombre sin S.L./S.A.) van siempre a revisar.
  Las fotos de mala calidad salen como `error` ("pide una foto más nítida").
- Facturas manuscritas y tickets: no previstos.
- No comprueba que el `nif_cliente` sea el del cliente al que pertenece el remitente (siguiente paso útil).
- No hay clasificación por categoría de gasto ni entrada por WhatsApp todavía.
- Nada ejecuta `correo` solo: hay que lanzarlo con cron o un workflow programado.

## Antes de usar facturas reales

- `facturas_datos/` está en `.gitignore`: no la subáis nunca al repositorio.
- Con `gemini` o `claude` las facturas salen a un tercero: contrato de tratamiento de datos y revisar
  la retención del proveedor antes de procesar facturas de clientes. `local` y `ollama` no tienen ese problema.
- Fijad un límite de gasto en la cuenta de la API.
- El buzón debe ser dedicado, con contraseña de aplicación.
