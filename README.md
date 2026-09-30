# Agente IA de Recuperación de Llamadas para Clínicas

Backend en FastAPI que convierte llamadas perdidas en citas. Cuando la centralita de una
clínica pierde una llamada, el sistema manda un WhatsApp de disculpa al paciente y, cuando
contesta, un modelo de Google Gemini responde usando los datos reales de esa clínica
(horarios, tarifas, personalidad) e intenta cerrar la cita.

## Cómo funciona

```
Llamada perdida                    Paciente responde
       │                                    │
       ▼                                    ▼
POST /api/llamada-perdida          POST /api/webhook/whatsapp
       │                                    │
       ├─ crea paciente                     ├─ busca conversación abierta
       ├─ abre conversación                 ├─ carga los últimos 8 mensajes
       └─ manda WhatsApp de disculpa        ├─ Gemini responde con el contexto
                                            └─ manda la respuesta por WhatsApp
```

Dos proveedores de WhatsApp son posibles: Evolution API, Baileys o Meta Cloud API.

## Requisitos

- Python 3.11 o superior
- Un proyecto de Supabase
- Una API key de Google Gemini (gratis en <https://aistudio.google.com/>)
- Opcional: una instancia de Evolution API para el envío real

## Puesta en marcha

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # y rellena los valores
```

### 1. Crear el esquema

Ejecuta `schema.sql` en el SQL Editor de tu proyecto de Supabase. Crea las cuatro tablas
(`clinicas`, `pacientes`, `conversaciones`, `mensajes`) con sus índices y activa RLS.

### 2. Cargar la clínica de demostración

Ejecuta `seed_clinica.sql` en el mismo editor. Inserta la clínica dental de ejemplo con el
UUID fijo `a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11` que usan las rutas de demo.

### 3. Configurar las credenciales

```bash
# Generar el secreto del webhook
openssl rand -hex 32
```

En `.env` necesitas:

| Variable | Para qué |
|---|---|
| `SUPABASE_URL` | URL de tu proyecto |
| `SUPABASE_KEY` | **Service role key**, no la anon |
| `GEMINI_API_KEY` | Clave de Gemini |
| `GEMINI_MODELS` | Modelos a probar, en orden |
| `WEBHOOK_SECRET` | Secreto que valida el webhook |

> **Usa la service role key.** La clave `anon` no puede escribir en las tablas: el agente
> registrará pacientes en memoria y nada llegará a la base de datos. La service role está
> en *Settings → API* dentro de tu proyecto de Supabase.

> **`WEBHOOK_SECRET` es obligatorio en producción.** Si se deja vacío, el endpoint de
> entrada se cierra y devuelve `503`. Nadie debería poder gastar tu cuota de Gemini.

### 4. Arrancar

```bash
python main.py          # o: uvicorn main:app --reload
```

Abre <http://localhost:8000> para la demo y <http://localhost:8000/docs> para la referencia
de la API. `GET /api/health` indica qué dependencias están configuradas.

## Rutas

| Ruta | Qué hace |
|---|---|
| `POST /api/llamada-perdida` | Disparador 1. Registra el paciente y manda el WhatsApp inicial. |
| `POST /api/webhook/whatsapp` | Disparador 2. Recibe la respuesta del paciente y contesta con Gemini. Exige `X-Webhook-Secret`. |
| `POST /api/demo/simular-llamada` | Simula una llamada perdida sin centralita. |
| `POST /api/demo/mensaje` | Simula la respuesta del paciente sin Evolution API. |
| `GET /api/health` | Estado de Supabase, Gemini y WhatsApp. |

### Probar el flujo completo sin WhatsApp

```bash
# 1. Dispara la llamada perdida
curl -X POST "http://localhost:8000/api/demo/simular-llamada?telefono=+34612345678"

# 2. El paciente "responde"
curl -X POST "http://localhost:8000/api/demo/mensaje?mensaje=Hola,+¿cuánto+cuesta+una+limpieza?"

# 3. Comprueba que se guardó
curl "http://localhost:8000/api/health"
```

Mientras `WHATSAPP_API_URL` esté vacío, los mensajes salientes se imprimen en la consola en
lugar de enviarse.

## Conectar WhatsApp real

Deja estas variables en `.env`:

```bash
WHATSAPP_API_URL=http://localhost:8080   # tu instancia de Evolution API
WHATSAPP_API_KEY=tu-api-key
WHATSAPP_INSTANCE_NAME=clinica_demo
```

El envío usa `POST {WHATSAPP_API_URL}/message/sendText/{INSTANCE}` con la cabecera `apikey`.

Configura en Evolution API un webhook que apunte a `https://tu-dominio/api/webhook/whatsapp`
con la cabecera `X-Webhook-Secret` y el campo `clinica_id` en el cuerpo, para que el agente
sepa a qué clínica pertenece cada conversación.

## Estructura

```
├── main.py               Rutas FastAPI, webhook, autenticación
├── database.py           Cliente de Supabase sobre su API REST
├── gemini_service.py     Llamadas a Gemini con cadena de modelos
├── whatsapp_service.py   Envío por Evolution API (o simulador)
├── config.py             Configuración desde el entorno
├── schema.sql            Tablas, índices y RLS
├── seed_clinica.sql      Clínica de demostración
├── test_gemini_service.py Pruebas de la lógica de reintentos
└── landing/index.html    Demo comercial
```

## Notas de operación

**Modelos de Gemini.** `GEMINI_MODELS` es una lista con prioridad. Si un modelo devuelve un
error recuperable (retirado o caído), se prueba el siguiente automáticamente.

**La cuota no es por modelo, es por proyecto.** En el nivel gratuito de Google, la cuota se
aplica al proyecto entero, no a cada modelo. Configurar tres modelos no da tres veces más
cuota. Si la API devuelve `429`, el agente lo detecta y **deja de probar modelos**: insistir
solo gastaría peticiones. Los límites se pueden consultar en
<https://aistudio.google.com/rate-limit>.

**Respuestas cortadas.** Los modelos flash reservan parte de `maxOutputTokens` para razonar
en silencio. Con un valor bajo, `finishReason` llega como `MAX_TOKENS` y el paciente recibe
una frase a medias. Por eso `GEMINI_MAX_OUTPUT_TOKENS` está en 1024 y
`GEMINI_THINKING_BUDGET` en 0: no hace falta razonar para contestar un WhatsApp.

Además, el servicio comprueba que cada respuesta termine en puntuación. Si aun así llega
cortada, reintenta con el doble de presupuesto antes de darla por buena. Un paciente
nunca debería recibir un texto a medias.

**Pruebas.** `test_gemini_service.py` verifica la lógica de reintentos con un doble de
prueba, sin gastar cuota:

```bash
./venv/bin/python test_gemini_service.py
```

**Historial.** Cada respuesta incluye los últimos 8 mensajes en orden cronológico. Si la IA
queda sin contexto útil, revisa `get_historial` en `database.py`.

**Latencia.** Cada petición al webhook encadena varias llamadas HTTP a Supabase y Gemini.
Con una base de datos real, la respuesta completa suele tardar entre 2 y 6 segundos. Si
necesitas respuesta inmediata para tu proveedor de WhatsApp, usa una cola de trabajos en
lugar de responder de forma síncrona.

**Privacidad.** Las conversaciones incluyen datos de pacientes: nombre y número de teléfono.
Es información de salud bajo el RGPD. Las tablas tienen RLS activo y el acceso del backend
es solo con la service role key. Define una política de retención antes de entrar en
producción.

**Métricas de negocio.** La conversación pasa a `ia_activa` al primer intercambio. Añade
transiciones a `cita_agendada` o `requiere_humano` cuando conectes una agenda real.
