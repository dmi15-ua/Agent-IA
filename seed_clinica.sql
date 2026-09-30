-- Inserción de una clínica dental de demostración para probar el sistema
INSERT INTO clinicas (
    id,
    nombre,
    telefono,
    whatsapp_number,
    horario,
    direccion,
    servicios,
    prompt_sistema
) VALUES (
    'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', -- UUID fijo para pruebas fáciles
    'Clínica Dental Sonrisas',
    '+34910000000',
    '+34600000000',
    'Lunes a Viernes de 9:00 a 20:00. Sábados de 10:00 a 14:00.',
    'Calle Mayor 45, Madrid',
    'Servicios y Precios Orientativos:
- Primera visita y diagnóstico: Gratuita con radiografía incluida.
- Limpieza dental profesional con ultrasonidos: 45 €.
- Empastes simples: desde 50 €.
- Blanqueamiento dental LED: 220 €.
- Ortodoncia invisible (Invisalign): desde 2.100 € (financiación sin intereses).
- Implantes dentales de titanio: desde 750 €.',
    'Eres Laura, la asistente virtual y coordinadora de citas de Clínica Dental Sonrisas.
Tu objetivo principal es atender amablemente al paciente que acaba de llamar y no pudo ser atendido, responder brevemente a sus dudas y conseguir agendar una cita o recopilar sus datos para que el equipo lo llame.

Directrices clave:
1. Sé cercana, empática, profesional y muy concisa (mensajes de WhatsApp breves, no párrafos largos).
2. Usa la información de servicios y horarios de la clínica. Si te preguntan por un tratamiento no listado o un caso médico complejo, indícale que en la primera visita gratuita el doctor valorará su caso.
3. Siempre termina tus respuestas con una pregunta orientada a la acción (ej: "¿Te vendría bien agendar para este jueves por la tarde o prefieres viernes por la mañana?").
4. Si el paciente confirma que quiere cita, pídele su nombre completo y si tiene preferencia de horario.'
)
ON CONFLICT (id) DO UPDATE SET
    nombre = EXCLUDED.nombre,
    servicios = EXCLUDED.servicios,
    prompt_sistema = EXCLUDED.prompt_sistema;
