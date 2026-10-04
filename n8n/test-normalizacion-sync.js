// Comprueba que la normalizacion de n8n (JS) y la del backend (Python) dan
// exactamente el mismo resultado. Si divergen, un mismo paciente podria acabar
// con dos fichas segun por donde entre la llamada, que es justo el bug que se
// arreglo en utils.py.
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const wf = JSON.parse(fs.readFileSync(
  path.join(__dirname, 'workflows', 'clinicas-llamadas-perdidas.json'), 'utf8'));
const jsLimpiar = wf.nodes.find((n) => n.name === 'Limpiar telefono').parameters.jsCode;

function normalizaJs(telefono) {
  const $input = { first: () => ({ json: { telefono, proveedor: 't', motivo: 't' } }) };
  try {
    return new Function('$input', jsLimpiar)($input)[0].json.telefono;
  } catch {
    return null;
  }
}

const casos = [
  '+34600112233', ' 34612345678', '34600112233', '600112233', '0034600112233',
  '+34 600 112 233', '+34-600-112-233', '(600) 112 233', '+44 20 7123 4567',
  '440207123456', '+1 202 555 0133', '12025550133', '+34600999000', '600999000',
  '+34612345678', '  +34 600 11 22 33  ', '0034600999000', '+34600112233 ',
  '+34 600112233', '34600112233;ext=1', '+34\t600 112 233', '91 123 45 67',
  '+34911234567', '911234567', '60011223', '123456789', '+346001122334',
];

// Python: mismo criterio, invocado en el venv del proyecto.
const py = `
import sys, json
sys.path.insert(0, ${JSON.stringify(path.join(__dirname, '..'))})
from utils import normalizar_telefono
casos = json.loads(sys.argv[1])
print(json.dumps([normalizar_telefono(c) for c in casos], ensure_ascii=False))
`;
const pyOut = execFileSync(
  path.join(__dirname, '..', 'venv', 'bin', 'python'),
  ['-c', py, JSON.stringify(casos)],
  { encoding: 'utf8' }
);
const resPy = JSON.parse(pyOut);

let divergencias = 0;
console.log('entrada'.padEnd(24) + 'n8n (JS)'.padEnd(18) + 'backend (Python)');
for (let i = 0; i < casos.length; i++) {
  const js = normalizaJs(casos[i]);
  const pyv = resPy[i];
  const igual = js === pyv;
  if (!igual) divergencias++;
  console.log(
    JSON.stringify(casos[i]).padEnd(24) +
    String(js).padEnd(18) +
    String(pyv).padEnd(18) +
    (igual ? 'OK' : 'DIVERGE')
  );
}

console.log('\n' + (divergencias === 0
  ? 'Sin divergencias en ' + casos.length + ' casos.'
  : divergencias + ' DIVERGENCIAS de ' + casos.length + ' casos.'));
process.exit(divergencias === 0 ? 0 : 1);