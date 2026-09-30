import logging
import uuid
import httpx
from typing import Optional, Dict, Any, List
import config

logger = logging.getLogger(__name__)

class SupabaseClient:
    def __init__(self):
        self.url = config.SUPABASE_URL.rstrip("/")
        self.key = config.SUPABASE_KEY
        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }

    @property
    def modo_demo(self) -> bool:
        """True cuando no hay credenciales reales y trabajamos con datos simulados."""
        return not self.url or not self.key or "tu-proyecto" in self.url

    @staticmethod
    def clinica_demo(clinica_id: str) -> Dict[str, Any]:
        return {
            "id": clinica_id,
            "nombre": "Clínica Dental Sonrisas (Demo)",
            "horario": "Lunes a Viernes de 9:00 a 20:00",
            "servicios": "Limpiezas dentales (45€), Empastes (desde 50€), Implantes (750€).",
            "prompt_sistema": "Eres Laura, asistente de la clínica. Atiende con amabilidad y busca agendar la cita."
        }

    def _es_uuid(self, valor: str) -> bool:
        """Supabase espera UUIDs reales; los IDs de mock rompen los filtros."""
        try:
            uuid.UUID(str(valor))
            return True
        except (ValueError, AttributeError, TypeError):
            return False

    async def get_clinica(self, clinica_id: str) -> Optional[Dict[str, Any]]:
        """Obtiene los datos y el prompt de una clínica por su ID."""
        if self.modo_demo:
            logger.warning("Supabase no configurado; devolviendo datos simulados.")
            return self.clinica_demo(clinica_id)

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.url}/rest/v1/clinicas",
                    params={"id": f"eq.{clinica_id}", "select": "*"},
                    headers=self.headers
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data[0] if data else None
                logger.error(f"Error al obtener clínica {clinica_id}: {resp.status_code} - {resp.text}")
                return None
        except Exception as e:
            logger.warning(f"Error de conexión a Supabase ({e}). Usando datos simulados.")
            return self.clinica_demo(clinica_id)


    async def get_or_create_paciente(self, clinica_id: str, telefono: str, nombre: Optional[str] = None) -> Dict[str, Any]:
        """Busca un paciente por teléfono y clínica o lo crea si es nuevo."""
        if self.modo_demo:
            return {"id": "mock-paciente-id", "clinica_id": clinica_id, "telefono": telefono, "nombre": nombre}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # 1. Buscar si ya existe
                resp = await client.get(
                    f"{self.url}/rest/v1/pacientes",
                    params={
                        "clinica_id": f"eq.{clinica_id}",
                        "telefono": f"eq.{telefono}",
                        "select": "*",
                    },
                    headers=self.headers
                )
                if resp.status_code == 200:
                    existing = resp.json()
                    if existing:
                        return existing[0]
                else:
                    logger.error(f"Error al buscar paciente: {resp.status_code} - {resp.text}")

                # 2. Si no existe, crearlo
                payload = {"clinica_id": clinica_id, "telefono": telefono}
                if nombre:
                    payload["nombre"] = nombre

                create_resp = await client.post(
                    f"{self.url}/rest/v1/pacientes",
                    headers=self.headers,
                    json=payload
                )
                if create_resp.status_code in (200, 201):
                    return create_resp.json()[0]

                logger.error(f"Error al crear paciente: {create_resp.status_code} - {create_resp.text}")
                raise RuntimeError(f"No se pudo crear el paciente ({create_resp.status_code})")
        except Exception as e:
            # Antes aquí se devolvía un id de mock y la petición continuaba como si
            # nada, ensuciando la base de datos y ocultando el fallo real.
            logger.error(f"Fallo en get_or_create_paciente: {e}")
            raise

    async def get_or_create_conversacion(self, clinica_id: str, paciente_id: str, origen: str = "llamada_perdida") -> Dict[str, Any]:
        """Obtiene la conversación activa reciente o crea una nueva."""
        if self.modo_demo:
            return {"id": "mock-conv-id", "paciente_id": paciente_id, "clinica_id": clinica_id, "estado": "nuevo_lead"}

        # Sin UUID válido no podemos filtrar por paciente_id: la consulta devolvería
        # un 400 y, además, podría traer conversaciones de otro paciente.
        if not self._es_uuid(paciente_id):
            logger.error(f"paciente_id inválido para Supabase: {paciente_id!r}")
            raise ValueError(f"paciente_id no es un UUID válido: {paciente_id!r}")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Buscar conversación no cerrada
                resp = await client.get(
                    f"{self.url}/rest/v1/conversaciones",
                    params={
                        "clinica_id": f"eq.{clinica_id}",
                        "paciente_id": f"eq.{paciente_id}",
                        "estado": "neq.cerrada",
                        "order": "created_at.desc",
                        "limit": "1",
                        "select": "*",
                    },
                    headers=self.headers
                )
                if resp.status_code == 200:
                    convs = resp.json()
                    if convs:
                        return convs[0]
                else:
                    logger.error(f"Error al buscar conversación: {resp.status_code} - {resp.text}")

                # Si no hay activa, crear una nueva
                create_resp = await client.post(
                    f"{self.url}/rest/v1/conversaciones",
                    headers=self.headers,
                    json={
                        "clinica_id": clinica_id,
                        "paciente_id": paciente_id,
                        "estado": "nuevo_lead",
                        "origen": origen
                    }
                )
                if create_resp.status_code in (200, 201):
                    return create_resp.json()[0]

                logger.error(f"Error al crear conversación: {create_resp.status_code} - {create_resp.text}")
                raise RuntimeError(f"No se pudo crear la conversación ({create_resp.status_code})")
        except Exception as e:
            logger.error(f"Fallo en get_or_create_conversacion: {e}")
            raise

    async def guardar_mensaje(self, conversacion_id: str, rol: str, contenido: str) -> bool:
        """Guarda un mensaje en la tabla mensajes."""
        if self.modo_demo:
            logger.info(f"[DB MOCK] Mensaje guardado ({rol}): {contenido}")
            return True

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.url}/rest/v1/mensajes",
                    headers=self.headers,
                    json={
                        "conversacion_id": conversacion_id,
                        "rol": rol,
                        "contenido": contenido
                    }
                )
                return resp.status_code in (200, 201)
        except Exception:
            return True

    async def get_historial(self, conversacion_id: str, limit: int = 8) -> List[Dict[str, str]]:
        """Recupera los ÚLTIMOS mensajes de la conversación, en orden cronológico.

        Pedimos los más recientes en descending y luego los giramos, porque pedir
        ascendentemente con un límite devolvería siempre los más antiguos.
        """
        if self.modo_demo:
            return []

        if not self._es_uuid(conversacion_id):
            logger.error(f"conversacion_id inválido para Supabase: {conversacion_id!r}")
            return []

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.url}/rest/v1/mensajes",
                    params={
                        "conversacion_id": f"eq.{conversacion_id}",
                        "order": "created_at.desc",
                        "limit": str(limit),
                        "select": "rol,contenido,created_at",
                    },
                    headers=self.headers
                )
                if resp.status_code == 200:
                    # Devolverlos del más antiguo al más reciente para que el
                    # modelo lea la conversación en orden.
                    return list(reversed(resp.json()))
                logger.error(f"Error al obtener historial: {resp.status_code} - {resp.text}")
                return []
        except Exception as e:
            logger.error(f"Fallo en get_historial: {e}")
            return []

    async def actualizar_estado_conversacion(self, conversacion_id: str, nuevo_estado: str):
        """Actualiza el estado de la conversación (ej: 'ia_activa', 'requiere_humano', 'cita_agendada')."""
        if self.modo_demo:
            return

        if not self._es_uuid(conversacion_id):
            logger.error(f"conversacion_id inválido para actualizar estado: {conversacion_id!r}")
            return

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.patch(
                    f"{self.url}/rest/v1/conversaciones",
                    params={"id": f"eq.{conversacion_id}"},
                    headers=self.headers,
                    json={"estado": nuevo_estado}
                )
        except Exception as e:
            logger.error(f"Fallo al actualizar estado de la conversación: {e}")


db = SupabaseClient()
