-- ============================================================
-- Altas desde la web: leads y onboarding de clínicas
-- Ejecutar en el SQL Editor de Supabase (una sola vez).
-- Es seguro volver a ejecutarlo.
-- ============================================================

-- 5. Leads: los formularios de la landing.
-- Una fila por persona que pide que le contacten. NO es lo mismo que un
-- paciente: un lead todavia no ha Denndo ningun telefono al agente.
CREATE TABLE IF NOT EXISTS public.leads (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Campos del formulario, tal cual los manda el visitante.
    clinica_nombre  TEXT NOT NULL,
    contacto_nombre TEXT,
    telefono        TEXT NOT NULL,
    especialidad    TEXT,
    -- A donde ha llegado desde la landing, para saber que funciona.
    origen          TEXT,
    -- Donde esta la solicitud: nuevo | contactado | demo_pedida | descartado
    estado          TEXT NOT NULL DEFAULT 'nuevo',
    -- Que leactoring vamos a contarle al equipo comercial.
    notas           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- El formulario se rellena mucho y desde el mismo numero llega mas de una
-- vez. Sin este indice, cada envio barre la tabla entera.
CREATE INDEX IF NOT EXISTS idx_leads_created ON public.leads(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_leads_estado ON public.leads(estado);

-- Ojo: aquí NO se pone un índice único por clínica y día como cuarta a la
-- intuition. Deduplicar con date_trunc('day', created_at) no funciona,
-- porque date_trunc no es IMMUTABLE y Postgres rechaza el índice. La
-- deduplicación se hace en el backend, que mira si hay un lead igual en las
-- últimas 24 horas.

-- 6. Alta de clinica: servicios, precios e instrucciones.
-- Es una solicitud de onboarding, no una clinica operativa. Se crea con
-- activo=false y alguien la revisa y activa. Por eso NO se escribe en la
-- tabla clinicas directamente: aqui se queda todo lo que el formulario pide,
-- incluidos los campos que clinicas todavia no tiene.
CREATE TABLE IF NOT EXISTS public.altas_clinica (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Quién la pide y cómo le contactamos.
    clinica_nombre     TEXT NOT NULL,
    contacto_nombre    TEXT,
    telefono           TEXT NOT NULL,
    email              TEXT,
    especialidad       TEXT,

    -- Lo que la IA necesita saber para no inventar.
    horario            TEXT,
    direccion          TEXT,
    whatsapp_number    TEXT,
    -- Precios y servicios, en texto libre. Ejemplo:
    --   "Limpieza 45 EUR. Empaste desde 50 EUR. Corb crown 300 EUR."
    servicios          TEXT,
    -- Personalidad del asistente y reglas del negocio.
    instrucciones      TEXT,
    -- Lo que NO puede decir la IA: descuentos que no existen, financiacion,
    -- seguros... Para que la IA se abstenga antes de prometer.
    prohibiciones      TEXT,

    -- Estado de la solicitud: pendiente | revisada | activada | descartada
    estado             TEXT NOT NULL DEFAULT 'pendiente',
    -- Cuando se aprueba, la clinica en public.clinicas que se ha creado.
    clinica_id         UUID REFERENCES public.clinicas(id) ON DELETE SET NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    revisada_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_altas_created ON public.altas_clinica(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_altas_estado ON public.altas_clinica(estado);

-- ============================================================
-- Row Level Security de las tablas nuevas
-- ============================================================
-- El backend usa la service_role key, que ignora estas políticas, asi que los
-- formularios funcionan. Lo que se cierra es el acceso directo desde el
-- navegador con la anon key: sin esto, cualquiera que sacase la anon key
-- podría leer los teléfonos de los leads que se han dado de alta.
-- ============================================================

ALTER TABLE public.leads         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.altas_clinica ENABLE ROW LEVEL SECURITY;

-- Sin políticas, a propósito: con RLS activo y sin política, la anon key no
-- lee ni escribe. Mismo criterio que las tablas del esquema original.