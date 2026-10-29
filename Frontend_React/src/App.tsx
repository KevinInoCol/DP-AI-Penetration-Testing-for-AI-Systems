import { useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import ReactMarkdown from 'react-markdown'
import { cargarHistorial, enviarMensaje } from './api.ts'
import type { Mensaje } from './api.ts'

// El session_id se guarda en el navegador para que, al recargar, la conversación
// siga en el mismo hilo (la memoria vive en Postgres, del lado del agente).
const CLAVE_SESION = 'tramibot.session_id'

const SUGERENCIAS = [
  '¿Qué necesito para el certificado de residencia?',
  '¿Cuánto tarda la licencia urbanística?',
  '¿A qué secretaría pertenece el impuesto predial?',
  'Quiero hablar con un funcionario',
]

function leerSesion(): string | null {
  try {
    return localStorage.getItem(CLAVE_SESION)
  } catch {
    return null
  }
}

function guardarSesion(sessionId: string | null) {
  try {
    if (sessionId) localStorage.setItem(CLAVE_SESION, sessionId)
    else localStorage.removeItem(CLAVE_SESION)
  } catch {
    // modo privado o almacenamiento bloqueado: la sesión dura lo que la pestaña
  }
}

export default function App() {
  const [sessionId, setSessionId] = useState<string | null>(leerSesion)
  const [mensajes, setMensajes] = useState<Mensaje[]>([])
  const [texto, setTexto] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [cargando, setCargando] = useState(Boolean(sessionId))
  const finRef = useRef<HTMLDivElement>(null)
  const entradaRef = useRef<HTMLTextAreaElement>(null)

  // Recuperar la conversación guardada al abrir la página
  useEffect(() => {
    if (!sessionId) return
    let activo = true
    cargarHistorial(sessionId)
      .then((previos) => activo && setMensajes(previos))
      .catch(() => activo && setMensajes([]))
      .finally(() => activo && setCargando(false))
    return () => {
      activo = false
    }
    // Solo al montar: después, los mensajes nuevos se agregan localmente
  }, [])

  useEffect(() => {
    finRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [mensajes, enviando])

  async function enviar(contenido: string) {
    const limpio = contenido.trim()
    if (!limpio || enviando) return
    setTexto('')
    setMensajes((prev) => [...prev, { rol: 'usuario', texto: limpio }])
    setEnviando(true)
    try {
      const res = await enviarMensaje(limpio, sessionId)
      if (res.session_id !== sessionId) {
        setSessionId(res.session_id)
        guardarSesion(res.session_id)
      }
      setMensajes((prev) => [...prev, { rol: 'agente', texto: res.respuesta, bloqueado: res.bloqueado }])
    } catch (e) {
      const detalle = e instanceof Error ? e.message : 'No se pudo conectar con TramiBot.'
      setMensajes((prev) => [...prev, { rol: 'agente', texto: detalle, error: true }])
    } finally {
      setEnviando(false)
      entradaRef.current?.focus()
    }
  }

  function alEnviar(e: FormEvent) {
    e.preventDefault()
    enviar(texto)
  }

  function alTeclear(e: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter envía; Shift+Enter hace salto de línea
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      enviar(texto)
    }
  }

  function nuevaConversacion() {
    setSessionId(null)
    guardarSesion(null)
    setMensajes([])
    setTexto('')
    entradaRef.current?.focus()
  }

  const vacio = !cargando && mensajes.length === 0

  return (
    <div className="app">
      <header className="cabecera">
        <div className="marca">
          <div className="logo" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="22" height="22">
              <path d="M4 6h16v9a3 3 0 0 1-3 3h-6l-5 4v-4a2 2 0 0 1-2-2z" fill="currentColor" />
            </svg>
          </div>
          <div>
            <h1>TramiBot</h1>
            <p>Asistente de trámites · Municipio de Girardota</p>
          </div>
        </div>
        <button type="button" className="boton-secundario" onClick={nuevaConversacion} disabled={enviando}>
          Nueva conversación
        </button>
      </header>

      <main className="conversacion" aria-live="polite">
        <div className="hilo">
          {cargando && <p className="estado">Recuperando tu conversación…</p>}

          {vacio && (
            <section className="bienvenida">
              <h2>¿En qué trámite le puedo ayudar?</h2>
              <p>
                Le oriento sobre requisitos, documentos, tiempos de obtención y la dependencia responsable de los
                trámites de la Alcaldía.
              </p>
              <div className="sugerencias">
                {SUGERENCIAS.map((s) => (
                  <button key={s} type="button" className="sugerencia" onClick={() => enviar(s)}>
                    {s}
                  </button>
                ))}
              </div>
            </section>
          )}

          {mensajes.map((m, i) => (
            <div key={i} className={`fila fila-${m.rol}`}>
              <div
                className={['burbuja', `burbuja-${m.rol}`, m.bloqueado && 'burbuja-bloqueada', m.error && 'burbuja-error']
                  .filter(Boolean)
                  .join(' ')}
              >
                {m.bloqueado && <span className="etiqueta">Bloqueado por el guardrail</span>}
                {m.error && <span className="etiqueta">Error</span>}
                {m.rol === 'agente' ? <ReactMarkdown>{m.texto}</ReactMarkdown> : <p>{m.texto}</p>}
              </div>
            </div>
          ))}

          {enviando && (
            <div className="fila fila-agente">
              <div className="burbuja burbuja-agente escribiendo" aria-label="TramiBot está escribiendo">
                <span />
                <span />
                <span />
              </div>
            </div>
          )}
          <div ref={finRef} />
        </div>
      </main>

      <footer className="pie">
        <form className="compositor" onSubmit={alEnviar}>
          <textarea
            ref={entradaRef}
            value={texto}
            onChange={(e) => setTexto(e.target.value)}
            onKeyDown={alTeclear}
            placeholder="Escriba su consulta sobre un trámite…"
            rows={1}
            maxLength={2000}
            autoFocus
            aria-label="Mensaje"
          />
          <button type="submit" className="boton-enviar" disabled={!texto.trim() || enviando} aria-label="Enviar">
            <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
              <path d="M3 20.5 21 12 3 3.5l2.5 7.5L14 12l-8.5 1z" fill="currentColor" />
            </svg>
          </button>
        </form>
        <p className="aviso">
          No comparta datos personales (cédula, teléfono, claves). La información es orientativa; para casos
          particulares le derivamos a un funcionario.
        </p>
        {sessionId && <p className="sesion">Sesión {sessionId.slice(0, 8)}</p>}
      </footer>
    </div>
  )
}
