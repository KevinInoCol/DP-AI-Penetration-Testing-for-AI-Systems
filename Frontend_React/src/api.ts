// Cliente de la API de main_frontend_react.py. Las rutas son relativas (/api):
// en desarrollo las resuelve el proxy de Vite y en producción el propio backend.

export type Rol = 'usuario' | 'agente'

export interface Mensaje {
  rol: Rol
  texto: string
  bloqueado?: boolean
  error?: boolean
}

export interface RespuestaChat {
  respuesta: string
  session_id: string
  bloqueado: boolean
}

async function leerError(res: Response): Promise<string> {
  try {
    const datos = await res.json()
    if (typeof datos.detail === 'string') return datos.detail
  } catch {
    // respuesta sin JSON: usamos el mensaje genérico
  }
  return `El servidor respondió ${res.status}.`
}

export async function enviarMensaje(mensaje: string, sessionId: string | null): Promise<RespuestaChat> {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mensaje, session_id: sessionId }),
  })
  if (!res.ok) throw new Error(await leerError(res))
  return res.json()
}

export async function cargarHistorial(sessionId: string): Promise<Mensaje[]> {
  const res = await fetch(`/api/historial/${encodeURIComponent(sessionId)}`)
  if (!res.ok) throw new Error(await leerError(res))
  const datos: { mensajes: Mensaje[] } = await res.json()
  return datos.mensajes
}
