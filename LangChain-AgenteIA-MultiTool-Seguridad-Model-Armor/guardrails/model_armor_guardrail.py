"""
Guardrail con Model Armor (Google Cloud) para el Agente TramiBot.

Reemplaza las 8 capas del InputGuardrail propio por la API gestionada de
Model Armor, con la plantilla creada en la consola de Google Cloud:

  - Entrada: sanitize_user_prompt    → antes de que el mensaje llegue al agente
  - Salida:  sanitize_model_response → antes de que la respuesta llegue al usuario

Los filtros, niveles de confianza y el registro NO viven en el código: viven en
la plantilla  projects/<proyecto>/locations/<región>/templates/<id>.

Autenticación: cuenta de servicio del proyecto, con la ruta de su llave JSON en
GOOGLE_APPLICATION_CREDENTIALS dentro del .env (no toca las credenciales globales
de gcloud). En Cloud Run se usa la cuenta de servicio del servicio. La identidad
necesita el rol Model Armor User (roles/modelarmor.user).

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

import os
import logging
from typing import Tuple

from dotenv import load_dotenv, find_dotenv
from google.api_core.client_options import ClientOptions
from google.cloud import modelarmor_v1

load_dotenv(find_dotenv())

# ============================================================
# CONFIGURACIÓN (.env)
# ============================================================
MODEL_ARMOR_PROJECT = os.getenv("MODEL_ARMOR_PROJECT", "")
MODEL_ARMOR_LOCATION = os.getenv("MODEL_ARMOR_LOCATION", "us-central1")
MODEL_ARMOR_TEMPLATE = os.getenv("MODEL_ARMOR_TEMPLATE", "datapath-guardrail")

# La región de la plantilla define el endpoint (no se puede cambiar después)
MODEL_ARMOR_ENDPOINT = f"modelarmor.{MODEL_ARMOR_LOCATION}.rep.googleapis.com"
TEMPLATE_NAME = (
    f"projects/{MODEL_ARMOR_PROJECT}/locations/{MODEL_ARMOR_LOCATION}"
    f"/templates/{MODEL_ARMOR_TEMPLATE}"
)
TIMEOUT_SECONDS = 10.0

# ============================================================
# FILTRO DE MODEL ARMOR → MOTIVO DE BLOQUEO
# ------------------------------------------------------------
# Cada filtro llega en un campo distinto de FilterResult. Se reutilizan los
# motivos del InputGuardrail original para que la web (main_frontend_react.py)
# y Red Turing los sigan entendiendo. El orden es la prioridad cuando saltan
# varios filtros a la vez.
# ============================================================
MOTIVO_POR_FILTRO = [
    ("pi_and_jailbreak_filter_result", "prompt_injection"),
    ("csam_filter_filter_result", "contenido_ia_bloqueado"),
    ("rai_filter_result", "contenido_toxico"),
    ("malicious_uri_filter_result", "url_maliciosa"),
    ("sdp_filter_result", "pii_detectado"),
    ("virus_scan_filter_result", "contenido_ia_bloqueado"),
]

MATCH_FOUND = modelarmor_v1.FilterMatchState.MATCH_FOUND

logger = logging.getLogger(__name__)

_client = None


def _get_client() -> modelarmor_v1.ModelArmorClient:
    """Cliente singleton (se crea en la primera llamada, no al importar)."""
    global _client
    if _client is None:
        _client = modelarmor_v1.ModelArmorClient(
            client_options=ClientOptions(api_endpoint=MODEL_ARMOR_ENDPOINT)
        )
    return _client


def _filtros_activados(resultado: modelarmor_v1.SanitizationResult) -> set:
    """Nombres de los campos de FilterResult que devolvieron MATCH_FOUND."""
    activados = set()
    for filtro in resultado.filter_results.values():
        for campo, _ in MOTIVO_POR_FILTRO:
            if campo not in filtro:
                continue
            detalle = getattr(filtro, campo)
            # Sensitive Data Protection guarda el veredicto un nivel más abajo
            if campo == "sdp_filter_result":
                detalle = detalle.inspect_result
            if detalle.match_state == MATCH_FOUND:
                activados.add(campo)
    return activados


def _motivo(resultado: modelarmor_v1.SanitizationResult) -> str:
    """"" si el mensaje es seguro; si no, el motivo del filtro con más prioridad."""
    if resultado.filter_match_state != MATCH_FOUND:
        return ""
    activados = _filtros_activados(resultado)
    for campo, motivo in MOTIVO_POR_FILTRO:
        if campo in activados:
            return motivo
    return "contenido_ia_bloqueado"


# ============================================================
# API pública — misma firma que el InputGuardrail original
# ============================================================
def verificar_input_guardrail(mensaje: str) -> Tuple[bool, str]:
    """
    Revisa el mensaje del usuario con sanitize_user_prompt.

    Returns:
        (True, "")      → mensaje seguro, pasa al agente
        (False, motivo) → mensaje bloqueado
    """
    if not mensaje or not mensaje.strip():
        return True, ""

    try:
        respuesta = _get_client().sanitize_user_prompt(
            request=modelarmor_v1.SanitizeUserPromptRequest(
                name=TEMPLATE_NAME,
                user_prompt_data=modelarmor_v1.DataItem(text=mensaje),
            ),
            timeout=TIMEOUT_SECONDS,
        )
    except Exception as e:
        # Fail-closed: si Model Armor no responde, no se deja pasar el mensaje
        logger.error(f"[MODEL ARMOR] Error en sanitize_user_prompt: {e}")
        return False, "servicio_no_disponible"

    motivo = _motivo(respuesta.sanitization_result)
    if motivo:
        logger.warning(f"[MODEL ARMOR] Entrada bloqueada: {motivo}")
        return False, motivo
    return True, ""


def verificar_output_guardrail(respuesta_agente: str, mensaje_usuario: str = "") -> Tuple[bool, str]:
    """
    Revisa la respuesta del agente con sanitize_model_response antes de enviarla.

    El prompt del usuario se envía como contexto para que Model Armor evalúe
    la respuesta en relación con lo que se preguntó.

    Returns:
        (True, "")                    → respuesta segura
        (False, "respuesta_insegura") → no se envía al usuario
    """
    if not respuesta_agente or not respuesta_agente.strip():
        return True, ""

    try:
        respuesta = _get_client().sanitize_model_response(
            request=modelarmor_v1.SanitizeModelResponseRequest(
                name=TEMPLATE_NAME,
                model_response_data=modelarmor_v1.DataItem(text=respuesta_agente),
                user_prompt=mensaje_usuario,
            ),
            timeout=TIMEOUT_SECONDS,
        )
    except Exception as e:
        logger.error(f"[MODEL ARMOR] Error en sanitize_model_response: {e}")
        return False, "servicio_no_disponible"

    motivo = _motivo(respuesta.sanitization_result)
    if motivo:
        logger.warning(f"[MODEL ARMOR] Salida bloqueada: {motivo}")
        return False, "respuesta_insegura"
    return True, ""


def respuesta_bloqueada(motivo: str = "") -> str:
    """Retorna el mensaje apropiado al usuario según el motivo del bloqueo."""
    mensajes = {
        "prompt_injection": (
            "Lo siento, no puedo procesar ese mensaje. "
            "Por favor, reformula tu pregunta de manera apropiada. "
            "Estoy aquí para ayudarte con los trámites y servicios del Municipio de Girardota."
        ),
        "contenido_toxico": (
            "Lo siento, no puedo continuar con esa conversación. "
            "Tu mensaje contiene contenido inapropiado. "
            "Por favor, mantén un trato respetuoso. Estoy aquí para ayudarte con los trámites del Municipio de Girardota."
        ),
        "pii_detectado": (
            "Lo siento, tu mensaje contiene información sensible (tarjetas, credenciales, etc.). "
            "Por seguridad, no compartas datos privados en el chat. "
            "Escribe tu consulta sin incluir esa información."
        ),
        "url_maliciosa": (
            "Lo siento, tu mensaje contiene un enlace que puede ser malicioso. "
            "Por favor, escribe tu consulta sin incluir ese link. "
            "Estoy aquí para ayudarte con los trámites del Municipio de Girardota."
        ),
        "contenido_ia_bloqueado": (
            "Lo siento, no puedo continuar con esa conversación. "
            "Tu mensaje contiene contenido que no puedo procesar. "
            "Estoy aquí para ayudarte con los trámites del Municipio de Girardota."
        ),
        "respuesta_insegura": (
            "Lo siento, no puedo darte esa respuesta. "
            "Por favor, reformula tu consulta sobre los trámites del Municipio de Girardota."
        ),
        "servicio_no_disponible": (
            "Lo siento, el servicio de seguridad no está disponible en este momento. "
            "Por favor, intenta de nuevo más tarde."
        ),
    }
    return mensajes.get(
        motivo,
        "Lo siento, no puedo procesar ese mensaje. "
        "Por favor, reformula tu pregunta de manera apropiada.",
    )
