"""Prueba de extremo a extremo del agente, de verdad.

Arranca contra un backend real (local o el de Railway) y comprueba el flujo
completo: llamada perdida -> WhatsApp -> respuesta del paciente -> respuesta
de la IA -> persistencia en Supabase.

    python test_flujo_completo.py
    python test_flujo_completo.py --url https://agent-ia-production-ed00.up.railway.app
    python test_flujo_completo.py --url http://localhost:8000

Importante: escribe datos de prueba en Supabase y los borra al terminar. Usa
un teléfono fijo reservado para esto, que se purga al empezar y al acabar, para
que una ejecucion interrumpida no deje basura.

Lo que NO comprueba: que el WhatsApp llegue de verdad al telefono. Eso hay que
mirarlo en el movil. Aqui solo se ve lo que devuelve la API.
"""
import argparse
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx
from dotenv import load_dotenv

load_dotenv()

# Telefono de pruebas. No usar el de un paciente real: el script manda
# WhatsApps de verdad si el backend tiene configurado Evolution API.
TELEFONO_PRUEBA = "+34600000000"
CLINICA = "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"

# Frases que la version antigua del codigo descartaba por no acabar en
# puntuacion, y acababan en el mensaje de "problema tecnico".
FRASES_SIN_PUNTO = [
    "Hola",
    "Perfecto, nos vemos",
    "vale",
    "Si",
    "Son 45 euros",
]

VERDE, ROJO, GRIS, FIN = "\033[32m", "\033[31m", "\033[90m", "\033[0m"

fallos = 0
avisos = 0


def comprobar(descripcion, condicion, detalle=""):
    global fallos
    if condicion:
        print(f"  {VERDE}OK{FIN}    {descripcion}")
    else:
        print(f"  {ROJO}FALLO{FIN} {descripcion}" + (f"\n         -> {detalle}" if detalle else ""))
        fallos += 1
    return bool(condicion)


def avisar(descripcion):
    global avisos
    print(f"  {GRIS}AVISO{FIN} {descripcion}")
    avisos += 1


def seccion(titulo):
    print(f"\n{GRIS}── {titulo}{FIN}")


# ---------------------------------------------------------------- Supabase

def supabase():
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_KEY", "")
    if not url or not key:
        print(f"{ROJO}Falta SUPABASE_URL o SUPABASE_KEY en el .env{FIN}")
        sys.exit(2)
    return httpx.Client(timeout=20, headers={
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }), url


def purgar(cli, url):
    """Borra todo lo del telefono de pruebas. Necesario antes y despues: si una
    ejecucion anterior se corto a mitad, sin esto el script leeria datos viejos
    y daria un OK falso."""
    pacientes = cli.get(f"{url}/rest/v1/pacientes",
                        params={"telefono": f"eq.{TELEFONO_PRUEBA}", "select": "id"},
                        headers=cli.headers).json()
    ids = [p["id"] for p in pacientes]
    if not ids:
        return 0
    conv = [c["id"] for c in cli.get(f"{url}/rest/v1/conversaciones",
              params={"paciente_id": f"in.({','.join(ids)})", "select": "id"},
              headers=cli.headers).json()]
    if conv:
        msgs = [m["id"] for m in cli.get(f"{url}/rest/v1/mensajes",
                  params={"conversacion_id": f"in.({','.join(conv)})", "select": "id"},
                  headers=cli.headers).json()]
        if msgs:
            cli.delete(f"{url}/rest/v1/mensajes",
                       params={"id": f"in.({','.join(msgs)})"}, headers=cli.headers)
        cli.delete(f"{url}/rest/v1/conversaciones",
                   params={"id": f"in.({','.join(conv)})"}, headers=cli.headers)
    cli.delete(f"{url}/rest/v1/pacientes",
               params={"id": f"in.({','.join(ids)})"}, headers=cli.headers)
    return len(ids)


def leer_historial(cli, url, telefono):
    """Devuelve los mensajes del paciente en orden cronologico."""
    pacientes = cli.get(f"{url}/rest/v1/pacientes",
                        params={"telefono": f"eq.{telefono}", "select": "id"},
                        headers=cli.headers).json()
    if not pacientes:
        return []
    conv = cli.get(f"{url}/rest/v1/conversaciones",
                   params={"paciente_id": f"eq.{pacientes[0]['id']}", "select": "id"},
                   headers=cli.headers).json()
    if not conv:
        return []
    filas = cli.get(f"{url}/rest/v1/mensajes",
                    params={"conversacion_id": f"eq.{conv[0]['id']}",
                            "order": "created_at.asc", "select": "rol,contenido"},
                    headers=cli.headers).json()
    return filas


# ---------------------------------------------------------------- API

def llamar(cli, base, ruta, secreto, cuerpo=None, params=None):
    cab = {"Content-Type": "application/json"}
    if secreto:
        cab["X-Webhook-Secret"] = secreto
    try:
        r = cli.post(f"{base}{ruta}", headers=cab, json=cuerpo or {}, params=params)
        return r.status_code, r.json()
    except urllib.error.HTTPError as e:  # pragma: no cover
        return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)}


def llamar_gemini():
    """Una peticion minima a Gemini para ver si queda cuota. El nivel gratuito
    son 20 peticiones diarias por modelo, asi que este dato es el que decide si
    el flujo completo puede funcionar hoy."""
    key = os.getenv("GEMINI_API_KEY", "")
    modelo = (os.getenv("GEMINI_MODELS", "gemini-2.5-flash").split(",")[0]).strip()
    cuerpo = {
        "contents": [{"role": "user", "parts": [{"text": "di hola"}]}],
        "generationConfig": {"temperature": 0.5, "maxOutputTokens": 64},
    }
    try:
        r = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent",
            params={"key": key}, json=cuerpo, timeout=30)
        if r.status_code == 200:
            return 200, "ok"
        return r.status_code, r.text[:300]
    except Exception as e:
        return 0, str(e)


def main():
    global fallos
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    args = ap.parse_args()
    base = args.url.rstrip("/")

    secreto = os.getenv("WEBHOOK_SECRET", "")
    if not secreto:
        print(f"{ROJO}Falta WEBHOOK_SECRET en el .env{FIN}")
        sys.exit(2)

    print(f"\nProbando contra: {base}")
    print(f"Supabase:       {os.getenv('SUPABASE_URL','').replace('https://','')}")

    cli, sb = supabase()
    purgar(cli, sb)
    http = httpx.Client(timeout=90)

    try:
        # ------------------------------------------------------ 1. disponibilidad
        seccion("1. El backend responde")
        try:
            r = http.get(f"{base}/api/health")
            health = r.json()
            comprobar("GET /api/health da 200", r.status_code == 200, f"dio {r.status_code}")
        except Exception as e:
            comprobar("GET /api/health da 200", False, str(e))
            print(f"\n{ROJO}No hay ningun backend en {base}.{FIN}")
            print("  Local:  cd ~/Documentos/agente-clinicas && "
                  "venv/bin/python -m uvicorn main:app --port 8000")
            sys.exit(1)

        seccion("2. Configuracion declarada")
        comprobar("Supabase configurado", health.get("supabase") == "configurado",
                  f"dice '{health.get('supabase')}'")
        comprobar("Gemini configurado", health.get("gemini") == "configurado",
                  f"dice '{health.get('gemini')}'")
        modelos = health.get("modelos_gemini") or []
        comprobar("Hay un modelo de respaldo", len(modelos) >= 2,
                  f"solo hay {modelos}")
        if "gemini-2.5-flash-lite" in modelos:
            comprobar("El modelo de respaldo NO esta retirado", False,
                      "gemini-2.5-flash-lite devuelve 404; usa gemini-3.5-flash-lite")
        if health.get("whatsapp") == "modo simulación":
            avisar("WhatsApp en modo simulacion: no se envia nada de verdad. "
                   "En produccion deberia decir 'configurado'.")

        seccion("3. Cuota de Gemini (la causa mas frecuente de fallos)")
        # Se comprueba antes de nada lo de la cuota, porque el nivel gratuito
        # son 20 peticiones DIARIAS por modelo. Cuando se agota, todas las
        # respuestas salen con el texto de emergencia: por eso el agente
        # "a veces va" y por eso parece que no funciona.
        cod_quo, cuerpo_quo = llamar_gemini()
        if cod_quo == 200:
            comprobar("Gemini responde (quota disponible)", True)
        elif cod_quo == 429:
            print(f"  {ROJO}FALLO{FIN} Cuota de Gemini AGOTADA")
            print(f"         -> {cuerpo_quo[:240]}")
            print(f"         {GRIS}Es la razon mas probable de que el agente falle.{FIN}")
            fallos += 1
        else:
            avisar(f"Gemini devolvio HTTP {cod_quo} al probar la cuota: {cuerpo_quo[:140]}")

        # ------------------------------------------------------ 3. seguridad
        seccion("4. Las rutas que mandan WhatsApp exigen secreto")
        for ruta, cuerpo in [
            ("/api/llamada-perdida",
             {"clinica_id": CLINICA, "telefono": TELEFONO_PRUEBA}),
            ("/api/demo/simular-llamada", {}),
            ("/api/demo/mensaje", {}),
            ("/api/webhook/whatsapp",
             {"telefono": TELEFONO_PRUEBA, "mensaje": "hola"}),
        ]:
            if ruta.startswith("/api/demo/mensaje"):
                cod, _ = llamar(http, base, ruta, None,
                                params={"mensaje": "hola", "telefono": TELEFONO_PRUEBA})
            elif ruta.startswith("/api/demo/simular"):
                cod, _ = llamar(http, base, ruta, None,
                                params={"telefono": TELEFONO_PRUEBA})
            else:
                cod, _ = llamar(http, base, ruta, None, cuerpo=cuerpo)
            comprobar(f"{ruta} sin secreto -> 401", cod == 401, f"dio {cod}")

        # ------------------------------------------------------ 4. llamada perdida
        seccion("5. Llamada perdida")
        cod, r = llamar(http, base, "/api/llamada-perdida", secreto,
                        cuerpo={"clinica_id": CLINICA, "telefono": "600000000",
                                "nombre": "Paciente Prueba"})
        comprobar("Se acepta la llamada perdida -> 200", cod == 200, f"dio {cod}: {r}")
        comprobar("Devuelve conversacion_id", bool(r.get("conversacion_id")), str(r))
        comprobar("Devuelve paciente_id", bool(r.get("paciente_id")), str(r))

        # El numero fue '600000000' y debe guardarse ya normalizado.
        guardados = cli.get(f"{sb}/rest/v1/pacientes",
                            params={"telefono": f"eq.{TELEFONO_PRUEBA}",
                                    "select": "id,telefono,nombre"}, headers=cli.headers).json()
        comprobar("El telefono se guarda normalizado (+34...)",
                  bool(guardados) and guardados[0]["telefono"].startswith("+34"),
                  f"guardado como {guardados[0]['telefono'] if guardados else 'nada'}")

        # ------------------------------------------------------ 5. conversación
        seccion("6. El paciente responde y la IA contesta")
        for frase in FRASES_SIN_PUNTO:
            cod, r = llamar(http, base, "/api/webhook/whatsapp", secreto,
                            cuerpo={"telefono": TELEFONO_PRUEBA, "mensaje": frase})
            resp = r.get("respuesta_generada", "")
            ok = cod == 200 and bool(resp)
            comprobar(f"Paciente dice {frase!r} -> respuesta real",
                      ok and "problema técnico" not in resp,
                      f"HTTP {cod}, respuesta: {resp[:80]!r}")
            if ok:
                print(f"         {GRIS}{resp[:100]}{FIN}")

        # ------------------------------------------------------ 6. persistencia
        seccion("7. Todo queda guardado en Supabase")
        hist = leer_historial(cli, sb, TELEFONO_PRUEBA)
        comprobar("Hay mensajes en el historial", len(hist) >= 3, f"hay {len(hist)}")
        n_user = sum(1 for m in hist if m["rol"] == "user")
        n_ia = sum(1 for m in hist if m["rol"] == "assistant")
        comprobar("Se guardan los mensajes del paciente", n_user >= 3, f"hay {n_user}")
        comprobar("Se guardan las respuestas de la IA", n_ia >= 3, f"hay {n_ia}")

        estados = cli.get(f"{sb}/rest/v1/conversaciones",
                          params={"paciente_id": f"eq.{guardados[0]['id']}",
                                  "select": "estado"}, headers=cli.headers).json() if guardados and "id" in guardados[0] else []
        comprobar("La conversacion queda en estado 'ia_activa'",
                  any(e["estado"] == "ia_activa" for e in estados),
                  str([e["estado"] for e in estados]))

        flojos = [m for m in hist if "problema técnico" in (m["contenido"] or "")]
        comprobar("Ninguna respuesta es la de emergencia", not flojos,
                  f"{len(flojos)} mensaje(s) de emergencia")

    finally:
        seccion("8. Limpieza")
        n = purgar(cli, sb)
        print(f"  {GRIS}Borrados {n} paciente(s) de prueba.{FIN}")
        http.close()
        cli.close()

    print()
    if fallos:
        print(f"{ROJO}{fallos} COMPROBACION(ES) FALLIDA(S){FIN}"
              + (f" y {avisos} aviso(s)." if avisos else "."))
        sys.exit(1)
    print(f"{VERDE}TODO CORRECTO: el flujo completo funciona.{FIN}"
          + (f" ({avisos} aviso, no bloqueante)" if avisos else ""))
    print(f"{GRIS}Recuerda: esto no comprueba que el WhatsApp llegue al movil.{FIN}")


if __name__ == "__main__":
    main()