# Agente de facturas

Lee facturas (PDF o foto), marca **cada campo** como `ok`, `dudoso` o `no_leido`, comprueba lo
que se puede comprobar con código, detecta repetidas y deja todo en una hoja que revisa el
gestor. De ahí sale el CSV para el programa de contabilidad.

```
Correo (IMAP) / carpeta vigilada → adjunto guardado por remitente → ¿ya leído? (hash)
→ LECTOR → comprobaciones del código (NIF con dígito de control, IVA, sumas...)
→ cuenta contable aprendida por proveedor → duplicados → base de datos SQLite
→ revision.csv (el gestor confirma en Excel) → importacion.csv
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
python -m facturas correo               # baja los adjuntos de correos NO leídos y los procesa
python -m facturas vigilar entrada/     # procesa lo que vaya llegando a una carpeta (Ctrl+C para parar)
```

Muestra el progreso (`[2/4] factura.pdf ...`). Todo se guarda en `facturas_datos/facturas.db` (SQLite).

**Lo ya leído no se vuelve a leer.** Si llega el mismo archivo (mismo hash) no se llama al lector ni se
gasta API: queda como `repetida` apuntando a la factura original. Los `error` sí se reintentan.
`--reprocesar` fuerza la lectura. Si llega la misma factura en *otro* archivo (reenviada, otro PDF) se
detecta por la clave NIF del proveedor + número + total.

### Revisión y exportación (el gestor)

```bash
python -m facturas hoja          # escribe facturas_datos/revision.csv desde la base
# ... en Excel / Google Sheets: filtrar estado=revisar, mirar `a_revisar`, corregir datos,
#     escribir la `cuenta_contable` y cambiar el estado a `confirmada` ...
python -m facturas sincronizar   # guarda en la base lo que se cambió
python -m facturas exportar      # facturas_datos/importacion.csv con las confirmadas
python -m facturas confirmar 7 --cuenta 62900000   # alternativa sin Excel
```

Estados: `lista` · `revisar` · `error` (mirad `error` y `que_hacer`) · `repetida` · `confirmada`.
`--incluir-listas` en `exportar` añade las `lista` sin revisión humana. Las columnas del CSV de
importación están en `hoja.COLUMNAS_IMPORTACION`: adaptadlas al programa de contabilidad.
Cuidado al guardar en Excel: si cambia el formato de los números (`100.00` → `100,00`), `sincronizar` lo verá como una corrección.

### Cuenta contable por proveedor (aprendizaje)

- Proveedor nuevo: la factura va a `revisar` ("hay que elegir la cuenta") y la elige una persona.
- Cada vez que se **confirma** una factura con la misma cuenta, suma una confirmación.
- Mientras tenga menos de 3 (`FACTURAS_CONFIRMACIONES_CUENTA`), el sistema la propone pero la factura
  sigue en `revisar` ("cuenta 62900000 sugerida, confirmada 1 de 3 veces").
- A la tercera, se fía: las facturas de ese proveedor pueden quedar `lista` sin revisión.
- Si el gestor pone otra cuenta, se aprende la nueva y la cuenta atrás vuelve a 1.
- No se aprende de un NIF inválido (crearía un proveedor fantasma). `python -m facturas cuentas` las lista.

## Medir si acierta

```bash
python -m facturas leer tu_carpeta --lector ollama --salida resultados
python -m facturas comparar tu_carpeta/esperado.json resultados/resultado.json
```

Escribid a mano los valores correctos en un `esperado.json` junto a las facturas (solo los campos que
queráis comprobar). La cifra clave es **errores marcados como seguros**: un campo mal leído que se dio
por `ok` y se colaría sin revisión. **Debe ser 0.** Probad varios lectores con las mismas facturas.

### Juego de pruebas incluido: `ejemplos_variados/` (21 documentos)

Se genera con `python facturas/generar_ejemplos.py`. **Son facturas inventadas y fotos simuladas**
(giro, sombra, desenfoque, ruido, JPEG): detectan fallos genéricos, no sustituyen a facturas reales de
proveedores reales. Resultado actual con el lector `local`: **144 de 152 campos correctos (95 %) y
0 errores marcados como seguros**. Lo que pasa con cada tipo:

| Documento | Resultado | Notas |
| --- | --- | --- |
| Estándar S.L., IVA 4 %, exenta, importes con miles, fecha en texto, dos columnas, plantilla en inglés | `lista` | |
| PDF escaneado y fotos recta, torcida 5° y con sombra | `lista` | pasan por OCR |
| Dos tipos de IVA | `revisar` | lee solo una de las dos bases |
| Con descuento | `revisar` | confunde subtotal con base |
| Rectificativa (negativa) | `revisar` | duda entre el número y la referencia a la factura abonada |
| Autónomo con IRPF | `revisar` | datos correctos; sin S.L./S.A. el nombre del proveedor siempre es dudoso |
| Extranjeras (Francia, Reino Unido) | `revisar` | NIF de otro país no se puede validar |
| Ticket simplificado | `revisar` | no tiene cliente |
| Foto de baja resolución | `revisar` | importes ilegibles: `no_leido` |
| Foto torcida 9° + sombra + desenfoque | `error` | no se lee: se pide otra foto |
| Menú de restaurante | `error` | "no parece una factura" (correcto) |

Ningún caso dudoso se cuela como seguro. Los fallos de la lista son los que hay que mejorar con el
lector `ollama`/`gemini`/`claude` o con reglas; medidlos con el mismo comando.

## Comprobaciones del código

Campos obligatorios · NIF/CIF/NIE con su dígito o letra de control (comprueba que el número es posible, no que esté dado de alta) ·
fecha válida y no futura · moneda EUR · base + IVA = total (acepta también el caso con retención de
IRPF; tolerancia 2 céntimos) · desglose de IVA coherente (cuota = base × tipo, suma = totales) ·
tipos de IVA 0, 4, 5, 10 y 21 % (no cubre IGIC de Canarias: revisadlo con un asesor).

**NIF mal leído por el OCR.** Si el NIF no es válido, se prueban las confusiones típicas (8↔B, 0↔O/D,
1↔I, 5↔S, 6↔G...) y, **solo si hay una única corrección con control válido**, se propone (por ejemplo
`822334452` → `B22334452`). Siempre queda como `dudoso`, nunca `ok`, y el motivo dice qué se cambió.

## Fotos de móvil

Antes del OCR se quitan las sombras y se endereza el texto (`extraccion/imagen.py`, necesita `numpy`); el
OCR prueba la foto con y sin tratamiento y se queda con la que reconoce más palabras. Con las fotos
simuladas, una foto torcida 5° pasó de `error` a `lista`, y otra con 9° + sombra + desenfoque pasó de 0 a
32 palabras reconocidas (aun así sigue sin leerse la columna de importes). **No he podido probar un
modelo de Ollama que vea la imagen**: para decidir entre mejorar el tratamiento o usar visión hacen
falta fotos reales que fallen, y medirlas con `leer` + `comparar`.

## Lo que se sabe que falla o falta

- Probado solo con facturas ficticias. Con reales de otros diseños aparecerán fallos nuevos: es el objetivo de medir.
- `local`: no entiende la factura; las de autónomos (nombre sin S.L./S.A.) van siempre a revisar.
  Las fotos de mala calidad salen como `error` ("pide una foto más nítida").
- Facturas manuscritas y tickets: no previstos.
- No comprueba que el `nif_cliente` sea el del cliente al que pertenece el remitente (siguiente paso útil).
- No hay entrada por WhatsApp. La cuenta contable se aprende por proveedor, pero no se propone por tipo de gasto.
- La base es SQLite (un solo equipo). Para varias personas a la vez toca migrarla a Supabase (`almacen.py` aísla toda la persistencia).
- `correo` no corre solo: hay que lanzarlo con cron o un workflow programado (`vigilar` sí corre hasta Ctrl+C).
- Varias bases en la factura (dos tipos de IVA) y descuentos: la base sale `dudoso`, no se suma sola.

## Antes de usar facturas reales

- `facturas_datos/` está en `.gitignore`: no la subáis nunca al repositorio.
- Con `gemini` o `claude` las facturas salen a un tercero: contrato de tratamiento de datos y revisar
  la retención del proveedor antes de procesar facturas de clientes. `local` y `ollama` no tienen ese problema.
- Fijad un límite de gasto en la cuenta de la API.
- El buzón debe ser dedicado, con contraseña de aplicación.
