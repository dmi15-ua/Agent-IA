"""Prueba real contra Gemini con el prompt de la clinica, sin tocar Supabase.

Envía varios mensajes encadenados como si fueran una conversación de WhatsApp y
comprueba que las respuestas NO llegan cortadas. Es la verificación que faltaba
tras cambiar el presupuesto de tokens.

Uso:
    ./venv/bin/python test_prompt.py

Ayuda a calibrar GEMINI_MAX_OUTPUT_TOKENS. Si salen truncadas, sube el valor.
"""
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx

import config
from gemini_service import _parece_truncada
from gemini_service import GeminiService

# Mismos datos que la clínica de demostración en Supabase
CLINICA = {
    "nombre": "Clínica Dental Sonrisas",
    "horario": "Lunes a Viernes de 9:00 a 20:00. Sábados de 10:00 a 14:00.",
    "direccion": "Calle Mayor 45, Madrid",
    "servicios": """Servicios y Precios Orientativos:
- Primera visita y diagnóstico: Gratuita con radiografía incluida.
- Limpieza dental profesional con ultrasonidos: 45 €.
- Empastes simples: desde 50 €.
- Blanqueamiento dental LED: 220 €.
- Ortodoncia invisible (Invisalign): desde 2.100 € (financiación sin intereses).
- Implantes dentales de titanio: desde 750 €.""",
    "prompt_sistema": """Eres Laura, la asistente virtual y coordinadora de citas de Clínica Dental Sonrisas.
Tu objetivo principal es atender amablemente al paciente que acaba de llamar y no pudo ser atendido, responder brevemente a sus dudas y conseguir agendar una cita o recopilar sus datos para que el equipo lo llame.

Directrices clave:
1. Sé cercana, empática, profesional y muy concisa (mensajes de WhatsApp breves, no párrafos largos).
2. Usa la información de servicios y horarios de la clínica. Si te preguntan por un tratamiento no listado o un caso médico complejo, indícale que en la primera visita gratuita el doctor valorará su caso.
3. Siempre termina tus respuestas con una pregunta orientada a la acción.
4. Si el paciente confirma que quiere cita, pídele su nombre completo y si tiene preferencia de horario.""",
}

CONVERSACION = [
    "Hola, ¿cuánto cuesta una limpieza?",
    "¿Tenéis parking para pacientes?",
    "¿Aceptáis el seguro Sanitas?",
    "Pues agendámelo el jueves por la mañana",
    "Me llamo Carlos García",
    "¿El implante me va a doler mucho?",
    "¿Hacéis descuento si vengo con mi hermano?",
]


async def main():
    print("Configuración en uso:")
    print("  modelos :", config.GEMINI_MODELS)
    print("  tokens  :", config.GEMINI_MAX_OUTPUT_TOKENS)
    print("  thinking:", config.GEMINI_THINKING_BUDGET)
    print()

    servicio = GeminiService()
    historial = []

    cortadas = 0
    inventadas = 0

    for pregunta in CONVERSACION:
        respuesta = await servicio.generar_respuesta(CLINICA, historial, pregunta)
        historial.append({"rol": "user", "contenido": pregunta})
        historial.append({"rol": "assistant", "contenido": respuesta})

        truncada = _parece_truncada(respuesta)
        if truncada:
            cortadas += 1

        marca = "  [CORTADA]" if truncada else ""
        print("PACIENTE: %s" % pregunta)
        print("LAURA   : %s%s" % (respuesta, marca))
        print()

        # Si la IA se compromete con algo que la clinica no ha dicho, es invencion
        if any(p in respuesta.lower() for p in ("no tenemos", "no aceptamos", "no hay")):
            inventadas += 1
            print("   ^ REVISAR: parece afirmar algo que no consta en los datos")
            print()

    print("=" * 70)
    print("RESUMEN")
    print("  respuestas cortadas : %d/%d" % (cortadas, len(CONVERSACION)))
    print("  a revisar           : %d/%d" % (inventadas, len(CONVERSACION)))
    print("=" * 70)

    return 1 if cortadas else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
