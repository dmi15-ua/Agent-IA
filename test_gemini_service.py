"""Prueba la logica de reintentos de gemini_service con un doble de httpx.

El doble consume las respuestas programadas EN ORDEN: la primera llamada recibe
la primera regla, la segunda la segunda, y asi sucesivamente. Asi se puede
comprobar exactamente que peticiones hace el codigo y con que resultado.
"""
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
logging.disable(logging.CRITICAL)

import config

COLA = []          # respuestas programadas, se consumen en orden
CALLS = []         # (modelo, max_output_tokens) de cada peticion


class RespuestaFalsa:
    def __init__(self, status_code, texto_json=None, texto=""):
        self.status_code = status_code
        self._json = texto_json
        self.text = texto or (str(texto_json) if texto_json else "")

    def json(self):
        return self._json


def texto_modelo(txt, finish="STOP"):
    return {"candidates": [{"content": {"parts": [{"text": txt}]}, "finishReason": finish}]}


def vacio(finish="STOP"):
    return {"candidates": [{"content": {"parts": []}, "finishReason": finish}]}


class ClienteFalso:
    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kw):
        modelo = url.split("/models/")[1].split(":")[0]
        max_tok = kw["json"]["generationConfig"]["maxOutputTokens"]
        CALLS.append((modelo, max_tok))
        if not COLA:
            raise AssertionError("el codigo hizo una llamada de mas: %s/%s" % (modelo, max_tok))
        return COLA.pop(0)


import httpx

httpx.AsyncClient = ClienteFalso

import gemini_service

gemini_service.httpx.AsyncClient = ClienteFalso

CLINICA = {"nombre": "Clinica Dental Sonrisas", "servicios": "Limpieza 45 EUR"}
EMERGENCIA = ("Hola, soy el asistente de Clinica Dental Sonrisas. "
              "Ahora mismo tengo un problema técnico para responderte. "
              "¿Puedes llamarnos de nuevo en un momento? Disculpa las molestias.")

M1, M2 = config.GEMINI_MODELS[0], config.GEMINI_MODELS[1]
N = config.GEMINI_MAX_OUTPUT_TOKENS

resultados = []


def check(nombre, respuestas, esperado, esperado_calls):
    COLA.clear()
    COLA.extend(respuestas)
    CALLS.clear()
    r = asyncio.run(gemini_service.gemini_ai.generar_respuesta(CLINICA, [], "hola"))
    ok = r == esperado and CALLS == esperado_calls
    resultados.append(ok)
    print("  %-52s %s" % (nombre, "OK" if ok else "FALLO"))
    if not ok:
        print("       obtenido : %r" % r)
        print("       esperado : %r" % esperado)
        print("       llamadas : %r" % (CALLS,))
        print("       esperadas: %r" % (esperado_calls,))


def ok200(txt, finish="STOP"):
    return RespuestaFalsa(200, texto_json=texto_modelo(txt, finish))


def http(status, cuerpo=""):
    return RespuestaFalsa(status, texto=cuerpo)


print("=" * 82)
print("LOGICA DE REINTENTOS DE GEMINI (doble de prueba, sin llamadas reales)")
print("=" * 82)
print()

check("1. respuesta buena -> una sola llamada",
      [ok200("Hola, ¿te ayudo?")],
      "Hola, ¿te ayudo?",
      [(M1, N)])

check("2. 503 en el primero -> cae al segundo modelo",
      [http(503, "demanda"), ok200("Perfecto.")],
      "Perfecto.",
      [(M1, N), (M2, N)])

check("3. MAX_TOKENS -> reintenta con doble presupuesto",
      [ok200("Consulta con el", "MAX_TOKENS"), ok200("Consulta con el equipo.")],
      "Consulta con el equipo.",
      [(M1, N), (M1, N * 2)])

check("4. cortada con finishReason=STOP -> tambien reintenta",
      [ok200("Sin punto final"), ok200("Con punto final.")],
      "Con punto final.",
      [(M1, N), (M1, N * 2)])

check("5. truncada dos veces -> pasa al segundo modelo",
      [ok200("A", "MAX_TOKENS"), ok200("B", "MAX_TOKENS"), ok200("Hola, ¿te agendo?")],
      "Hola, ¿te agendo?",
      [(M1, N), (M1, N * 2), (M2, N)])

check("6. 400 no recuperable -> para sin probar mas",
      [http(400, "payload invalido")],
      EMERGENCIA,
      [(M1, N)])

check("7. cuota agotada -> para sin gastar mas peticiones",
      [http(429, "cuota")],
      EMERGENCIA,
      [(M1, N)])

check("10. 429 en el segundo modelo -> para",
      [http(503, "caida"), http(429, "cuota")],
      EMERGENCIA,
      [(M1, N), (M2, N)])

check("8. vacio con STOP -> cambia de modelo, no reintenta",
      [RespuestaFalsa(200, texto_json=vacio("STOP")), ok200("Hola.")],
      "Hola.",
      [(M1, N), (M2, N)])

check("9. todo sale cortado -> emergencia, nunca texto cortado",
      [ok200("A"), ok200("B"), ok200("C"), ok200("D")],
      EMERGENCIA,
      [(M1, N), (M1, N * 2), (M2, N), (M2, N * 2)])

print()
print("=" * 82)
print("RESULTADO: %d/%d" % (sum(resultados), len(resultados)))
print("=" * 82)
sys.exit(0 if all(resultados) else 1)
