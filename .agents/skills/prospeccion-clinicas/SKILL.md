---
name: prospeccion-clinicas
description: Motor de prospección, auditoría y captación B2B de clínicas (dentales, estéticas, fisioterapia y salud) en España. Rastrea clínicas por ciudades o provincias, audita sus canales de contacto (Google Maps, web, WhatsApp, Instagram) y genera fichas de prospectos cualificados junto con mensajes de contacto personalizados listos para enviar (Estrategia de recuperación de llamadas perdidas). Usar cuando el usuario pida "buscar clínicas", "prospectar candidatos", "encontrar clientes en [ciudad]", "generar leads", "contactar clínicas" o "buscar candidatos en España".
---

# Motor de Prospección de Clínicas en España (B2B Lead Finder)

Esta skill permite al agente identificar, cualificar y preparar el contacto directo con clínicas en España para ofrecerles el servicio de **Recuperación de Llamadas Perdidas por WhatsApp**.

---

## 1. Perfil del Cliente Ideal (ICP - Ideal Customer Profile)

Priorizamos clínicas donde el retorno de inversión y el dolor de las llamadas no atendidas sea máximo:

1. **Especialidades con mayor ticket y demanda:**
   - **Clínicas Dentales:** Ortodoncia, implantes, estética dental (tickets de 70 € a 3.500 €).
   - **Medicina Estética y Dermatología:** Tratamientos láser, toxina, rellenos (tickets de 120 € a 1.200 €).
   - **Fisioterapia y Osteopatía:** Sesiones recurrentes y bonos (tickets de 45 € a 250 €).
   - **Clínicas Veterinarias o Podología.**

2. **Tipo de negocio:**
   - **Clínicas privadas independientes o grupos locales (1 a 3 centros):** Tienen dueños accesibles, toma de decisiones rápida y recepción propia.
   - **EVITAR al inicio:** Grandes franquicias multinacionales (ej. Vitaldent, Dorsia, Sanitas Dental) porque tienen centralitas corporativas rígidas y departamentos de compras complejos.

---

## 2. Flujo de Trabajo de Prospección

Cuando el usuario pida buscar candidatos en una ciudad o zona (ej: *"Busca 5 clínicas dentales en Valencia"*):

### Paso 1: Búsqueda Geográfica
Utiliza la herramienta de búsqueda web para rastrear clínicas en la ciudad especificada:
- Query: `"clinica dental [ciudad]" OR "clinica estetica [ciudad]" contactar whatsapp`
- Query: `"clinica fisioterapia [ciudad]" instagram`
- Localiza clínicas con presencia activa en Google Maps y web propia.

### Paso 2: Auditoría Rápida de Canales
Para cada clínica candidata, revisa su web o ficha de contacto buscando:
- **Teléfono móvil / WhatsApp:** ¿Tienen un número que empieza por 6 o 7 para citas?
- **Perfil de Instagram:** ¿Tienen cuenta activa con publicaciones en los últimos 30-60 días?
- **Horario:** ¿Cierran a mediodía (14:00 - 16:00) o los fines de semana? (Punto débil donde más llamadas pierden).
- **Atención web:** ¿Tienen ya algún bot o chat interactivo? (Si no tienen nada, son el candidato perfecto).

### Paso 3: Generación de la Ficha de Prospectos
Presenta al usuario una tabla clara y estructurada con los datos encontrados:

| Clínica | Ciudad / Zona | Teléfono / WhatsApp | Instagram | Contacto / Doctor | Potencial |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Clínica Dental X** | Valencia (Ruzafa) | +34 600 12 34 56 | @clinicadentalx | Dr. Carlos García | 🟢 Alto (Móvil en web, sin bot) |

---

## 3. Generación del Mensaje de Contacto (Estrategia 2)

Por cada clínica cualificada, redacta el mensaje de contacto listo para **copiar y pegar** adaptado a su canal principal (Instagram DM o WhatsApp).

### A. Para Instagram DM:
```text
¡Hola equipo de [Nombre de la clínica]! Enhorabuena por el trabajo que compartís por aquí, tenéis una clínica fantástica 👏

Os escribo con una pregunta rápida: ¿tenéis actualmente algún sistema que contacte por WhatsApp a los pacientes que os hacen una llamada perdida fuera de horario o cuando tenéis recepción ocupada?

He desarrollado una herramienta para clínicas de [Ciudad] para recuperar esas citas antes de que busquen a otra clínica en Google. Estamos activando una prueba de 14 días 100% gratuita a un par de clínicas de la zona para que lo prueben sin compromiso.

Si os encaja ver cómo funciona en un vídeo de 40 segundos, avisadme y os lo paso por aquí. ¡Un saludo!
```

### B. Para WhatsApp directo:
```text
Hola, buenos días. Os contacto porque vi vuestra clínica en Google y quería hacer una consulta al responsable de gestión de pacientes o recepción.

¿Tenéis algún sistema que atienda por WhatsApp a los pacientes que os dejan una llamada perdida cuando estáis ocupados en consulta o fuera de horario?

Ayudo a clínicas de [Ciudad] a no perder esas citas con un sistema que contacta al paciente en 15 segundos. Estamos ofreciendo una prueba gratuita de 14 días (sin coste ni permanencia) para que veáis en vuestro propio móvil cuántos pacientes recuperáis esta semana.

¿Con quién podría compartir un vídeo de 30 segundos demostrándolo?
```

---

## 4. Respuesta a Objeciones Típicas

Si una clínica responde con dudas, utiliza estas pautas:

- **Objeción:** *"Ya tenemos recepcionista que atiende las llamadas."*
  - **Respuesta:** *"¡Totalmente! El sistema no sustituye a la recepcionista, la ayuda precisamente en los momentos en que ella está cobrando o atendiendo a alguien en consulta y no puede descolgar una segunda línea simultánea."*
- **Objeción:** *"¿Cuánto cuesta después de los 14 días?"*
  - **Respuesta:** *"La tarifa es de solo 49 €/mes todo incluido. Si en los 14 días de prueba veis que os recupera al menos 1 o 2 pacientes (que ya pagan la cuota de sobra), genial; si no, lo desactivamos y no habéis gastado nada."*
- **Objeción:** *"¿Es difícil de instalar?"*
  - **Respuesta:** *"Para nada, la configuración la hacemos nosotros en 24 horas sin interrumpir vuestro día a día."*
