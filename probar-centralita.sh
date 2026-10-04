#!/usr/bin/env bash
# Prueba el disparo de "llamada perdida" contra el backend.
#
#   ./probar-centralita.sh                      -> contra el deploy de Railway
#   ./probar-centralita.sh http://localhost:8000 -> contra tu maquina
#   TELEFONO=600112233 ./probar-centralita.sh   -> con otro numero
#
# El secreto se lee del .env, asi que no hay que escribirlo aqui.
set -euo pipefail

# AVISO: contra el deploy real esto manda un WhatsApp de verdad al numero que
# pongas, a traves de Evolution API. Usa un numero tuyo o uno de pruebas.
cat <<'AVISO'

  ESTE SCRIPT MANDA UN WHATSAPP REAL AL NUMERO QUE INDIQUES.
  En produccion sale por Evolution API y llega a un telefono de verdad.

AVISO

BASE="${1:-https://agent-ia-production-ed00.up.railway.app}"
TELEFONO="${TELEFONO:-600112233}"
CLINICA="${CLINICA:-a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11}"
NOMBRE="${NOMBRE:-Paciente Prueba}"

if [ ! -f .env ]; then
    echo "No encuentro .env en $(pwd). Lanza el script desde la raiz del proyecto." >&2
    exit 1
fi

SECRET="$(grep -E '^WEBHOOK_SECRET=' .env | head -1 | cut -d= -f2-)"
if [ -z "$SECRET" ]; then
    echo "WEBHOOK_SECRET vacio o ausente en .env" >&2
    exit 1
fi

echo "-> $BASE/api/llamada-perdida"
echo "   telefono: $TELEFONO (se normalizara solo)"
echo
echo "   Respuesta:"
curl -sS -m 60 -X POST "$BASE/api/llamada-perdida" \
    -H "Content-Type: application/json" \
    -H "X-Webhook-Secret: $SECRET" \
    -d "{\"clinica_id\":\"$CLINICA\",\"telefono\":\"$TELEFONO\",\"nombre\":\"$NOMBRE\"}" \
    -w "\n   [HTTP %{http_code}]\n"
echo
echo "Si ves HTTP 401 -> el secreto no coincide con el del servidor."
echo "Si ves HTTP 200 -> la centralita ya esta lista para llamar asi."