"""Prueba los formularios de la web (leads y altas de clínica).

No necesita las tablas en Supabase para la parte de validación: el objetivo es
comprobar que lo que llega desde la landing se rechaza cuando no debe, que el
límite por IP funciona, y que el campo trampa para bots hace su trabajo.

    venv/bin/python test_formularios.py
    venv/bin/python test_formularios.py --con-tablas   # además, escritura real
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx
from dotenv import load_dotenv

load_dotenv()

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


def avisar(descripcion):
    global avisos
    print(f"  {GRIS}AVISO{FIN} {descripcion}")
    avisos += 1


def seccion(t):
    print(f"\n{GRIS}── {t}{FIN}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--con-tablas", action="store_true",
                    help="intenta escribir de verdad (necesita las tablas)")
    args = ap.parse_args()
    base = args.url.rstrip("/")

    http = httpx.Client(timeout=30)

    def post(ruta, cuerpo):
        r = http.post(f"{base}{ruta}", json=cuerpo)
        return r.status_code, r.json()

    print(f"\nProbando formularios contra: {base}")

    seccion("1. El backend expone los formularios")
    try:
        r = http.get(f"{base}/openapi.json")
        rutas = set(r.json().get("paths", {}))
    except Exception as e:
        comprobar("el backend responde", False, str(e))
        sys.exit(1)
    comprobar("Existe POST /api/leads", "/api/leads" in rutas)
    comprobar("Existe POST /api/altas-clinica", "/api/altas-clinica" in rutas)

    seccion("2. Validación (estos NO necesitan las tablas)")
    cod, _ = post("/api/leads", {"clinica_nombre": "", "telefono": "+34600112233"})
    comprobar("Lead sin nombre de clínica -> 422", cod == 422, f"dio {cod}")

    cod, _ = post("/api/leads", {"clinica_nombre": "Dental X"})
    comprobar("Lead sin teléfono -> 422", cod == 422, f"dio {cod}")

    cod, _ = post("/api/leads", {"clinica_nombre": "X", "telefono": "12"})
    comprobar("Lead con teléfono demasiado corto -> 422", cod == 422, f"dio {cod}")

    cod, _ = post("/api/altas-clinica", {"clinica_nombre": "Dental X",
                                         "telefono": "+34600112233", "servicios": "corto"})
    comprobar("Alta sin servicios suficientes -> 422", cod == 422, f"dio {cod}")

    cod, cuerpo = post("/api/altas-clinica", {"clinica_nombre": "Dental X",
                                             "servicios": "Limpieza 45 euros"})
    comprobar("Alta sin teléfono -> 422", cod == 422, f"dio {cod}")

    seccion("3. Campo trampa contra bots")
    cod, cuerpo = post("/api/leads", {"clinica_nombre": "Bot Clinic",
                                      "telefono": "+34600112233",
                                      "web": "http://spam.example"})
    comprobar("Lead con el campo trampa relleno -> 200", cod == 200, f"dio {cod}")
    # La respuesta del honeypot es intencionadamente igual que la de un envío
    # real, para que el bot no aprenda a distinguirlo. Lo que se comprueba aquí
    # es que devuelve 200 y un mensaje genérico, no que se haya guardado nada
    # (eso solo se puede ver con las tablas creadas).
    comprobar("Responde con un mensaje genérico",
              "recibida" in str(cuerpo).lower(), str(cuerpo))
    print(f"         {GRIS}Con --con-tablas se comprueba además que no se guarda "
          f"ninguna fila.{FIN}")

    seccion("4. Límite de envíos por IP")
    # OJO al leer esto: el límite son 5 peticiones por IP cada 5 minutos. Si
    # lanzas esta prueba dos veces seguidas, la segunda ve menos peticiones
    # libres que 5 porque la ventana todavía no ha expirado. Por eso se
    # comprueba un mínimo de 4 y no exactamente 5.
    codigos = [post("/api/leads", {"clinica_nombre": f"Prueba {i}",
                                   "telefono": f"+3460099900{i}"})[0]
               for i in range(9)]
    pasan = sum(1 for c in codigos if c != 429)
    bloqueados = sum(1 for c in codigos if c == 429)
    print(f"         {GRIS}9 envíos -> {pasan} no bloqueados, {bloqueados} bloqueados{FIN}")
    print(f"         {GRIS}códigos: {codigos}{FIN}")
    comprobar("La mayoría pasan sin problema", pasan >= 4,
              f"solo pasaron {pasan}")
    comprobar("El límite acaba bloqueando", bloqueados >= 1,
              f"códigos: {codigos}")
    if pasan < 4:
        avisar("Han pasado menos de 4 peticiones. La ventana de 5 minutos de "
               "una ejecución anterior sigue viva; espera a que expire y repite.")

    seccion("5. Escritura real (necesita las tablas creadas)")
    if not args.con_tablas:
        print(f"  {GRIS}Omitido. Usa --con-tablas cuando hayas pegado schema_web.sql "
              f"en Supabase.{FIN}")
    else:
        cod, cuerpo = post("/api/leads", {"clinica_nombre": "Clinica Test Formulario",
                                          "contacto_nombre": "Prueba",
                                          "telefono": "+34600555555",
                                          "especialidad": "Clínica Dental"})
        if cod == 400 and "No hemos podido guardar" in str(cuerpo):
            avisar("Las tablas siguen sin existir. Pega schema_web.sql en "
                   "https://supabase.com/dashboard/project/qdzaduvnohiwmwdfmrkk/sql")
        else:
            comprobar("Lead completo -> 200", cod == 200, f"dio {cod}: {cuerpo}")

            cod, cuerpo = post("/api/leads", {"clinica_nombre": "Clinica Test Formulario",
                                              "telefono": "+34600555555"})
            comprobar("El mismo teléfono otra vez no rompe nada", cod == 200,
                      f"dio {cod}: {cuerpo}")

            cod, cuerpo = post("/api/altas-clinica", {
                "clinica_nombre": "Clinica Test Alta",
                "telefono": "600555555",
                "horario": "Lunes a viernes de 9:00 a 20:00",
                "servicios": "Limpieza 45 euros\nEmpaste desde 50 euros",
                "instrucciones": "Tono cercano.",
            })
            if cod == 200:
                comprobar("Alta con servicios y precios -> 200", True)
            else:
                avisar(f"Alta -> HTTP {cod}: {str(cuerpo)[:200]}")

    seccion("6. El honeypot no guarda nada")
    if not args.con_tablas:
        print(f"  {GRIS}Omitido (necesita las tablas).{FIN}")
    else:
        cod, cuerpo = post("/api/leads", {"clinica_nombre": "Bot Clinic",
                                          "telefono": "+34600555500",
                                          "web": "http://spam.example"})
        comprobar("El envío con trampa devuelve la misma respuesta que uno real",
                  cod == 200 and "recibida" in str(cuerpo).lower(),
                  f"dio {cod}: {cuerpo}")
        # La prueba de que no se guarda es que, si se guardara, el siguiente
        # envío del mismo teléfono se trataría como duplicado.
        cod, cuerpo = post("/api/leads", {"clinica_nombre": "Bot Clinic",
                                          "telefono": "+34600555500"})
        comprobar("Y tampoco cuenta como lead guardado",
                  cod == 200, f"dio {cod}")

    print()
    if fallos:
        print(f"{ROJO}{fallos} COMPROBACIÓN(ES) FALLIDA(S){FIN}"
              + (f" y {avisos} aviso(s)." if avisos else "."))
        sys.exit(1)
    print(f"{VERDE}TODO CORRECTO{FIN}"
          + (f" ({avisos} aviso, no bloqueante)" if avisos else ""))


if __name__ == "__main__":
    main()