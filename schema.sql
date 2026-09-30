-- ============================================================
-- Esquema de la base de datos del Agente de Clínicas
-- Ejecutar en el SQL Editor de Supabase (una sola vez).
-- ============================================================

-- 1. Tabla de clínicas (multi-tenant: una fila por cliente)
CREATE TABLE IF NOT EXISTS public.clinicas (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre          TEXT NOT NULL,
    telefono        TEXT,
    whatsapp_number TEXT,
    horario         TEXT,
    direccion       TEXT,
    servicios       TEXT,
    -- Instrucciones de personalidad y reglas de negocio que inyecta la IA
    prompt_sistema  TEXT,
    activo          BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2. Pacientes (un registro por teléfono y clínica)
CREATE TABLE IF NOT EXISTS public.pacientes (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinica_id  UUID NOT NULL REFERENCES public.clinicas(id) ON DELETE CASCADE,
    telefono    TEXT NOT NULL,
    nombre      TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Evita duplicar al paciente si la centralita notifica dos veces la misma llamada
    CONSTRAINT pacientes_clinica_telefono_unico UNIQUE (clinica_id, telefono)
);

CREATE INDEX IF NOT EXISTS idx_pacientes_clinica ON public.pacientes(clinica_id);

-- 3. Conversaciones (una por paciente, reutilizable hasta que se cierre)
CREATE TABLE IF NOT EXISTS public.conversaciones (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinica_id  UUID NOT NULL REFERENCES public.clinicas(id) ON DELETE CASCADE,
    paciente_id UUID NOT NULL REFERENCES public.pacientes(id) ON DELETE CASCADE,
    estado      TEXT NOT NULL DEFAULT 'nuevo_lead',
    -- De dónde salió el contacto: llamada_perdida | whatsapp | manual
    origen      TEXT NOT NULL DEFAULT 'llamada_perdida',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    cerrada_at  TIMESTAMPTZ
);

-- Índices para la consulta que hace el agente en cada mensaje:
-- "conversación abierta de este paciente, la más reciente"
CREATE INDEX IF NOT EXISTS idx_conversaciones_paciente
    ON public.conversaciones(clinica_id, paciente_id, created_at DESC);

-- 4. Mensajes (historial completo de la conversación)
CREATE TABLE IF NOT EXISTS public.mensajes (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversacion_id  UUID NOT NULL REFERENCES public.conversaciones(id) ON DELETE CASCADE,
    -- user = paciente, assistant = IA
    rol              TEXT NOT NULL CHECK (rol IN ('user', 'assistant')),
    contenido        TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Soporta get_historial(): últimos N mensajes ordenados por fecha
CREATE INDEX IF NOT EXISTS idx_mensajes_conversacion
    ON public.mensajes(conversacion_id, created_at DESC);

-- ============================================================
-- Row Level Security
-- El backend usa la service_role key, que ignora estas políticas,
-- pero dejan las tablas cerradas si alguien accede desde el cliente.
-- ============================================================

ALTER TABLE public.clinicas      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pacientes     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversaciones ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mensajes      ENABLE ROW LEVEL SECURITY;

-- Sin políticas creadas a propósito: con RLS activo y sin política,
-- nadie puede leer ni escribir vía anon/authenticated. El acceso del
-- agente se hace siempre con la service_role key desde el backend.
