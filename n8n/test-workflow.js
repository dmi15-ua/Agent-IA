// Extrae el jsCode de cada nodo Code del workflow y lo ejecuta contra
// payloads reales, imitando lo que hace n8n ($input.first().json).
const fs = require('fs');
const path = require('path');

const wfPath = path.join(__dirname, 'workflows', 'clinicas-llamadas-perdidas.json');
const wf = JSON.parse(fs.readFileSync(wfPath, 'utf8'));

function codigoDe(nombreNodo) {
  const nodo = wf.nodes.find((n) => n.name === nombreNodo);
  if (!nodo) throw new Error('No existe el nodo ' + nombreNodo);
  return nodo.parameters.jsCode;
}

// n8n inyecta $input; aquí se simula con el mismo contrato ($input.first().json)
function ejecutar(js, body) {
  const $input = { first: () => ({ json: { body } }) };
  const fn = new Function('$input', js);
  const res = fn($input);
  return res[0].json;
}

function limpiarComoNodo(j) {
  const js = codigoDe('Limpiar telefono');
  const $input = { first: () => ({ json: j }) };
  const fn = new Function('$input', js);
  try {
    return { ok: true, tel: fn($input)[0].json.telefono };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

let fallos = 0;
function comprobar(descripcion, condicion, detalle) {
  if (condicion) {
    console.log('  OK    ' + descripcion);
  } else {
    console.log('  FALLO ' + descripcion + (detalle ? ' -> ' + detalle : ''));
    fallos++;
  }
}

console.log('=== TWILIO (form-encoded) ===');
const twilio = codigoDe('Twilio normalizar');
const casosTwilio = [
  ['no-answer', true, 'llamada perdida'],
  ['busy', true, 'linea ocupada'],
  ['failed', true, 'fallo de red'],
  ['completed', false, 'alguien descolgo'],
  ['in-progress', false, 'aun suena'],
  ['ringing', false, 'empezando a sonar'],
];
for (const [estado, esperado, nota] of casosTwilio) {
  const r = ejecutar(twilio, { CallStatus: estado, From: '+34600112233', CallSid: 'CAxxxx' });
  comprobar(estado.padEnd(12) + ' missed=' + esperado + ' (' + nota + ')', r.missed === esperado,
    'obtenido ' + r.missed);
}

console.log('\n=== TWILIO: body como texto plano (aslo llega de n8n) ===');
const rTexto = new Function('$input', twilio)(
  { first: () => ({ json: { body: 'CallSid=CA1&From=%2B34600112233&CallStatus=no-answer' } }) }
)[0].json;
comprobar('form como texto plano se parsea', rTexto.missed === true && rTexto.telefono === '+34600112233',
  JSON.stringify(rTexto));

console.log('\n=== TELNYX (JSON) ===');
const telnyx = codigoDe('Telnyx normalizar');
const casosTelnyx = [
  ['call.hangup', 'call_rejected', 'incoming', true, 'nadie descolgo'],
  ['call.hangup', 'normal_clearing', 'incoming', false, 'colgada normalmente'],
  ['call.hangup', 'call_rejected', 'outbound', false, 'saliendo, no entra'],
  ['call.initiated', null, 'incoming', false, 'solo empezo'],
  ['call.answered', null, 'incoming', false, 'contestada'],
];
for (const [evento, causa, direccion, esperado, nota] of casosTelnyx) {
  const body = {
    data: {
      event_type: evento,
      id: 'ev1',
      payload: {
        from: '+34600112233',
        to: '+34910000000',
        direction: direccion,
        hangup_cause: causa,
        call_session_id: 'sess1',
      },
    },
  };
  const r = ejecutar(telnyx, body);
  comprobar((evento + '/' + causa).padEnd(34) + ' missed=' + esperado + ' (' + nota + ')',
    r.missed === esperado, 'obtenido ' + r.missed);
}

console.log('\n=== GENERICO (contrato del backend) ===');
const gen = codigoDe('Generico normalizar');
const rGen = ejecutar(gen, { clinica_id: 'abc', telefono: '600112233', nombre: 'Ana' });
comprobar('respeta clinica_id', rGen.clinica_id === 'abc');
comprobar('respeta nombre', rGen.nombre === 'Ana');
comprobar('detecta el telefono', rGen.telefono === '600112233');
const rGenVacio = ejecutar(gen, {});
comprobar('sin telefono -> missed=false', rGenVacio.missed === false);
const rGenAlt = ejecutar(gen, { from: '+34600999000' });
comprobar('acepta campo "from"', rGenAlt.telefono === '+34600999000');

console.log('\n=== NORMALIZACION DE TELEFONO ===');
const casosTel = [
  ['+34600112233', '+34600112233'],
  [' 34612345678', '+34612345678'],
  ['34600112233', '+34600112233'],
  ['600112233', '+34600112233'],
  ['0034600112233', '+34600112233'],
  ['+34 600 112 233', '+34600112233'],
  ['+44 20 7123 4567', '+442071234567'],
  ['600999000', '+34600999000'],
];
for (const [entrada, esperado] of casosTel) {
  const r = limpiarComoNodo({ telefono: entrada, proveedor: 'test', motivo: 'test' });
  comprobar(JSON.stringify(entrada).padEnd(20) + ' -> ' + esperado, r.ok && r.tel === esperado,
    r.ok ? 'obtenido ' + r.tel : r.error);
}
const rSinTel = limpiarComoNodo({ telefono: '', proveedor: 'twilio', motivo: 'x' });
comprobar('telefono vacio -> error claro', !rSinTel.ok && /sin telefono legible/.test(rSinTel.error),
  rSinTel.error);

console.log('\n=== SINCRONIA CON utils.py (backend) ===');
const fs2 = require('fs');
const py = fs2.readFileSync(path.join(__dirname, '..', 'utils.py'), 'utf8');
comprobar('utils.py existe y menciona normalizar_telefono', /def normalizar_telefono/.test(py));

console.log('\n' + (fallos === 0 ? 'TODO CORRECTO: 0 fallos' : fallos + ' FALLOS'));
process.exit(fallos === 0 ? 0 : 1);