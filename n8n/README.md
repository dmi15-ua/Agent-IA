# Adaptador de centralitas (n8n)

Una capa delante del backend para que **da igual qué centralita tenga la clínica**.

El problema: cada centralita avisa de una llamada perdida de forma distinta.
Twilio manda `application/x-www-form-urlencoded`, Telnyx manda JSON con su
propia envoltura, Fonvirtual manda lo suyo, Asterisk avisa por AMI. Si el
backend quedara atado a una sola marca, solo podrías vender a clínicas que
tuvieran esa marca.

La solución: **n8n recibe el evento de quien sea y siempre habla el mismo idioma
con el backend**. El backend no se entera de nada.

```
Centralita ──► n8n ──► POST /api/llamada-perdida  ──►  Supabase
(clínica)     (normaliza)   (mismo JSON siempre)      + WhatsApp
```

## Puesta en marcha

```bash
cd n8n
docker compose up -d
```

1. Abre <http://localhost:5678> (usuario `admin`, contraseña `admin`).
2. **Credentials → New** → tipo **Header Auth**:
   - Name: `Backend Agente IA`
   - Header Name: `X-Webhook-Secret`
   - Header Value: tu `WEBHOOK_SECRET` (el mismo que tiene el backend)
3. **Workflows → Import from File** → `workflows/clinicas-llamadas-perdidas.json`
4. En el nodo **Avisar al backend**, selecciona la credencial que acabas de crear.

El workflow trae la URL de producción ya puesta
(`https://agent-ia-production-ed00.up.railway.app`). Si algún día usas otro
entorno, cámbiala ahí.

### Que las centralitas lleguen a n8n

n8n se levanta en `localhost`, que no existe para Internet. Necesitas una URL
pública:

- **En local**: `cloudflared tunnel --url http://localhost:5678` o
  `ngrok http 5678`, y usas la URL que te den.
- **En Railway**: despliega este mismo `docker-compose.yml` como un servicio
  aparte con su dominio, y pon `WEBHOOK_URL=https://tu-dominio/` en el entorno.

## Las tres entradas

| Webhook | Para quién | Qué espera |
|---|---|---|
| `POST /webhook/twilio/missed-call` | Twilio | form-encoded; mira `CallStatus` |
| `POST /webhook/telnyx/missed-call` | Telnyx | JSON; mira `data.event_type` y `hangup_cause` |
| `POST /webhook/generico/missed-call` | cualquier otra | el mismo JSON que el backend |

En la UI de n8n, cada nodo Webhook te muestra la URL exacta con la que
configurarlo en tu proveedor.

### Qué se considera "llamada perdida"

- **Twilio**: `no-answer`, `busy` y `failed`. Si `completed`, no hace nada.
- **Telnyx**: evento `call.hangup`, dirección `incoming` y una causa de la lista
  `CAUSAS_SIN_ATENDER`.

> **Ojo con Telnyx.** La causa que significa "nadie descolgó" depende de cómo
> tengas configurada la conexión. Antes de darlo por bueno: haz una llamada de
> prueba al número, mira el evento real en **Webhook Deliveries** de tu cuenta y
> ajusta `CAUSAS_SIN_ATENDER` en el nodo *Telnyx normalizar* si tu clínica
> devuelve otra.

## Para conectar una centralita nueva

1. Añade un nodo Webhook con un path nuevo, por ejemplo `mi-centralita/missed-call`.
2. Copia el nodo *Generico normalizar* y adapta los nombres de campo de tu
   centralita al contrato `{ clinica_id, telefono, nombre }`.
3. Conéctalo a **Era llamada perdida?**.

Eso es todo. No hay que tocar ni el backend ni `docker-compose.yml`.

## Pruebas

Hay dos scripts que se ejecutan con Node (no hace falta instalar nada más):

```bash
node test-workflow.js             # 24 casos: deteccion de llamada perdida y normalizacion
node test-normalizacion-sync.js   # 27 casos: que n8n y el backend den lo mismo
```

El segundo es el importante. Compara la función de limpieza de este directorio
con `utils.py` del backend. Si divergen, el mismo paciente podría acabar con dos
fichas según por dónde entre la llamada, que es exactamente el bug que se
arregló en `utils.py`. Si tocas cualquiera de las dos, pasa los dos scripts.

## Notas

- Los webhooks responden `200` en cuanto reciben el evento (`responseMode:
  onReceived`). La centralita no espera a que la IA conteste, y por eso no te
  reintenta el webhook si Gemini va lento.
- El nodo *Avisar al backend* reintenta 3 veces con 2 s de margen. Si el backend
  devuelve `401`, no reintenta (el secreto está mal, y reintentar no lo arregla).
- Los errores de la centralita se quedan en la lista de ejecuciones de n8n, que
  es más fácil de mirar que los logs de Railway.