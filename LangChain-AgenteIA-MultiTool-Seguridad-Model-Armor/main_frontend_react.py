"""
Integración del Agente IA con un Frontend web (React + Vite)
API REST para que la interfaz web (carpeta Frontend_React/, al lado de la carpeta
del agente) converse con TramiBot.

Es la segunda interfaz del mismo agente: usa el mismo chat_con_agente que el
webhook de Chatwoot (Model Armor en entrada y salida + RAG + memoria + Langfuse), pero sin
nada de Chatwoot (ni etiquetas ia-off, ni buffer de mensajes, ni handoff).

  POST /api/chat                   {"mensaje": "...", "session_id": "uuid opcional"}
                                   → {"respuesta", "session_id", "bloqueado"}
  GET  /api/historial/{session_id} → {"session_id", "mensajes": [{rol, texto}]}
  GET  /api/health

En desarrollo el frontend corre en Vite (puerto 5173) y llega a /api por proxy.
En producción (npm run build) este mismo servidor sirve ../Frontend_React/dist/
(o la ruta de FRONTEND_DIST_DIR).

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

import os
import sys
import uuid
import asyncio
import logging

from dotenv import load_dotenv, find_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

# Mostrar logs INFO de guardrails en consola
logging.basicConfig(level=logging.INFO, format="%(message)s")

load_dotenv(find_dotenv())

# Agregar el directorio actual al path (portable para despliegue)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agente_sec_langfuse import chat_con_agente
from chat_history import get_session_history
from guardrails.model_armor_guardrail import respuesta_bloqueada

# ============================================
# CONFIGURACIÓN
# ============================================
FRONTEND_PORT = int(os.getenv("FRONTEND_API_PORT", "8001"))
# Orígenes permitidos por CORS (solo hace falta si el front no usa el proxy de Vite)
FRONTEND_ORIGINS = [
    o.strip()
    for o in os.getenv("FRONTEND_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if o.strip()
]

CANAL = "web"
# El frontend vive junto a la carpeta del agente: <módulo>/Frontend_React/dist
DIST_DIR = os.getenv(
    "FRONTEND_DIST_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Frontend_React", "dist"),
)

# Motivos de bloqueo de Model Armor (guardrails/model_armor_guardrail.py).
# chat_con_agente devuelve solo el texto, así que reconocemos un bloqueo
# comparando con los mensajes de respuesta_bloqueada(). Si se agrega un motivo
# nuevo al guardrail, añádelo aquí para que la web lo marque como bloqueado.
MOTIVOS_BLOQUEO = [
    "prompt_injection", "contenido_toxico", "pii_detectado",
    "url_maliciosa", "contenido_ia_bloqueado", "respuesta_insegura",
    "servicio_no_disponible", "",
]
RESPUESTAS_BLOQUEO = {respuesta_bloqueada(m) for m in MOTIVOS_BLOQUEO}

# ============================================
# APP
# ============================================
app = FastAPI(title="TramiBot - API para Frontend React")

app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class ChatRequest(BaseModel):
    mensaje: str
    session_id: str | None = None


def _session_id_valido(session_id: str | None) -> str:
    """Devuelve el UUID recibido si es válido; si no, abre una sesión nueva."""
    try:
        return str(uuid.UUID(str(session_id or "").strip()))
    except ValueError:
        return str(uuid.uuid4())


@app.post("/api/chat")
async def chat(req: ChatRequest):
    mensaje = req.mensaje.strip()
    if not mensaje:
        raise HTTPException(status_code=400, detail="El mensaje está vacío.")

    session_id = _session_id_valido(req.session_id)
    print(f"💬 [WEB] {session_id[:8]} → {mensaje[:80]}")

    try:
        respuesta = await asyncio.to_thread(chat_con_agente, mensaje, session_id, None, CANAL)
    except Exception as e:
        print(f"   ❌ Error al procesar: {e}")
        raise HTTPException(
            status_code=500,
            detail="Tuve un problema al procesar tu consulta. Intenta de nuevo en un momento.",
        )

    return {
        "respuesta": respuesta,
        "session_id": session_id,
        "bloqueado": respuesta in RESPUESTAS_BLOQUEO,
    }


@app.get("/api/historial/{session_id}")
async def historial(session_id: str):
    """Mensajes guardados en Postgres para que la web recupere la conversación."""
    try:
        uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="session_id no es un UUID válido.")

    def _leer():
        history = get_session_history(session_id)
        return [
            {"rol": "usuario" if m.type == "human" else "agente", "texto": m.content}
            for m in history.messages
            if m.type in ("human", "ai")
        ]

    mensajes = await asyncio.to_thread(_leer)
    return {"session_id": session_id, "mensajes": mensajes}


@app.get("/api/health")
def health_check():
    return {"status": "healthy", "agent": "TramiBot", "canal": CANAL}


# En producción, el build de React se sirve desde la raíz (después de las rutas /api)
if os.path.isdir(DIST_DIR):
    app.mount("/", StaticFiles(directory=DIST_DIR, html=True), name="frontend")


# ============================================
# MAIN
# ============================================
if __name__ == "__main__":
    print()
    print("=" * 60)
    print("🚀 INICIANDO TRAMIBOT PARA EL FRONTEND REACT")
    print("=" * 60)
    print("🤖 Agente: TramiBot - Trámites del Municipio de Girardota (RAG + Memoria)")
    print("🔧 Tools: buscar_tramites, obtener_fecha_hora")
    print("💾 Historial: PostgreSQL")
    print(f"🌐 API: http://127.0.0.1:{FRONTEND_PORT}/api")
    print(f"🖥️  Build servido: {DIST_DIR if os.path.isdir(DIST_DIR) else 'no — usa npm run dev en ../Frontend_React'}")
    print("=" * 60)
    print()

    uvicorn.run(app, host="0.0.0.0", port=FRONTEND_PORT)
