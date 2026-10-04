"""Recepción de formularios desde la landing: leads y altas de clínica.

Estas rutas son públicas por naturaleza: las rellena cualquiera que abra la web.
Eso obliga a ser cuidadoso, porque una ruta sin protección es una puerta
abierta. Aquí se aplica lo mismo que en el resto del backend: el cliente nunca
toca la base de datos, solo llama a la API, y la API usa la service_role key.

Los precios y servicios no se guardan sueltos: se meten en la tabla
altas_clinica como una solicitud, y alguien la revisa antes de que exista la
clínica. Ver schema_web.sql.
"""
import logging
import time
from typing import Dict, List, Optional

import httpx

import config
from utils import normalizar_telefono

logger = logging.getLogger(__name__)

# Límite anti-abuso. Cuántas peticiones admite una misma IP en una ventana.
# Sin esto, cualquiera que descubriera la URL podría llenar la tabla de miles
# de filas falsas y, en el peor caso, disparar notificaciones.
MAX_PETICIONES = 5
VENTANA_SEGUNDOS = 300

# IP -> lista de timestamps de sus peticiones recientes.
_INTENTOS: Dict[str, List[float]] = {}


def _permitido(ip: str) -> bool:
    """True si esta IP puede pasar. Avisa en el log cuando se bloquea."""
    ahora = time.time()
    previos = [t for t in _INTENTOS.get(ip, []) if ahora - t < VENTANA_SEGUNDOS]
    if len(previos) >= MAX_PETICIONES:
        # Se guarda igual para que siga bloqueada mientras siga insistiendo.
        _INTENTOS[ip] = previos + [ahora]
        return False
    _INTENTOS[ip] = previos + [ahora]
    return True


def _limpiar_mapa() -> None:
    """Purga las IPs que ya no pueden volver a pasar. Sin esto el mapa crece
    sin límite en un proceso de larga vida."""
    ahora = time.time()
    caducadas = [ip for ip, ts in _INTENTOS.items()
                 if not ts or ahora - ts[-1] >= VENTANA_SEGUNDOS]
    for ip in caducadas:
        _INTENTOS.pop(ip, None)


class Formularios:
    def __init__(self):
        self.url = config.SUPABASE_URL.rstrip("/")
        self.key = config.SUPABASE_KEY
        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    @property
    def disponible(self) -> bool:
        return bool(self.url and self.key and "tu-proyecto" not in self.url)

    async def _post(self, tabla: str, payload: dict) -> Optional[dict]:
        if not self.disponible:
            logger.error("Supabase no configurado: no se puede guardar el formulario.")
            return None
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(f"{self.url}/rest/v1/{tabla}",
                                      headers=self.headers, json=payload)
                if r.status_code in (200, 201):
                    filas = r.json()
                    return filas[0] if filas else {}
                logger.error(f"No se pudo guardar en {tabla}: "
                             f"{r.status_code} - {r.text[:300]}")
                return None
        except Exception as e:
            logger.error(f"Fallo guardando en {tabla}: {e}")
            return None

    async def _ultimo_leadigual(self, telefono: str, horas: int = 24):
        """Busca un lead con el mismo teléfono en las últimas horas. Se usa para
        no crear tres filas cuando alguien manda el formulario tres veces."""
        if not self.disponible:
            return None
        desde = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                              time.gmtime(time.time() - horas * 3600))
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(
                    f"{self.url}/rest/v1/leads",
                    params={"telefono": f"eq.{telefono}",
                            "created_at": f"gte.{desde}",
                            "select": "id,clinica_nombre",
                            "limit": "1"},
                    headers=self.headers)
                if r.status_code == 200 and r.json():
                    return r.json()[0]
                return None
        except Exception as e:
            logger.warning(f"No se pudo comprobar el lead duplicado: {e}")
            return None

    async def crear_lead(self, clinica_nombre: str, telefono: str,
                         contacto_nombre: Optional[str] = None,
                         especialidad: Optional[str] = None,
                         origen: Optional[str] = None) -> tuple:
        """Guarda una solicitud de la landing. Devuelve (ok, mensaje)."""
        telefono = normalizar_telefono(telefono)
        if not telefono or len(telefono) < 8:
            return False, "El teléfono no parece válido."

        repetido = await self._ultimo_leadigual(telefono)
        if repetido:
            # No es un error: la respuesta es la misma para que el visitante no
            # piense que ha fallado algo. Pero no duplicamos la fila.
            logger.info(f"Lead repetido de {telefono}; no se crea otra fila.")
            return True, ("Ya nos constas esta solicitud. Te contactaremos muy "
                          "pronto.")

        fila = await self._post("leads", {
            "clinica_nombre": clinica_nombre,
            "contacto_nombre": contacto_nombre or None,
            "telefono": telefono,
            "especialidad": especialidad or None,
            "origen": origen or "landing",
        })
        if fila is None:
            return False, "No hemos podido guardar la solicitud. Inténtalo en un momento."
        logger.info(f"Lead nuevo: {clinica_nombre} ({telefono})")
        return True, "¡Solicitud recibida! Te contactaremos en menos de 24 horas."

    async def registrar_alta_clinica(self, datos: dict) -> tuple:
        """Guarda la ficha completa de una clínica: servicios, precios e instrucciones.

        No se activa la clínica aquí. Queda como pendiente hasta que alguien la
        revise, porque una IA con precios inventados es peor que no tener IA.
        """
        clinica_nombre = (datos.get("clinica_nombre") or "").strip()
        telefono = normalizar_telefono(datos.get("telefono") or "")

        if not clinica_nombre:
            return False, "Falta el nombre de la clínica."
        if not telefono or len(telefono) < 8:
            return False, "Falta un teléfono de contacto válido."
        servicios = (datos.get("servicios") or "").strip()
        if len(servicios) < 10:
            return False, "Necesitamos los servicios con sus precios para configurar la IA."

        payload = {
            "clinica_nombre": clinica_nombre,
            "contacto_nombre": (datos.get("contacto_nombre") or "").strip() or None,
            "telefono": telefono,
            "email": (datos.get("email") or "").strip() or None,
            "especialidad": (datos.get("especialidad") or "").strip() or None,
            "horario": (datos.get("horario") or "").strip() or None,
            "direccion": (datos.get("direccion") or "").strip() or None,
            "whatsapp_number": normalizar_telefono(datos.get("whatsapp_number") or "") or None,
            "servicios": servicios,
            "instrucciones": (datos.get("instrucciones") or "").strip() or None,
            "prohibiciones": (datos.get("prohibiciones") or "").strip() or None,
            "estado": "pendiente",
        }

        fila = await self._post("altas_clinica", payload)
        if fila is None:
            return False, "No hemos podido guardar la solicitud. Inténtalo en un momento."
        logger.info(f"Alta de clinica pendiente: {clinica_nombre} ({telefono})")
        return True, ("¡Recibido! Revisamos la ficha y te escribimos para "
                      "configurarla y probarla.")


formularios = Formularios()