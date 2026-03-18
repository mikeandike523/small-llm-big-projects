import { io, type Socket } from 'socket.io-client'

// Runtime config injected by serve.cjs via /runtime-config.js takes priority,
// then the Vite build-time env var, then a sensible default.
declare global {
  interface Window {
    __FLASK_URL__?: string
  }
}

const FLASK_URL =
  (typeof window !== 'undefined' && window.__FLASK_URL__)
    ? window.__FLASK_URL__
    : (import.meta.env.VITE_FLASK_URL ?? 'http://localhost:5000')

/**
 * Create a socket.io client for a specific session.
 * The socket is returned disconnected; call socket.connect() to open it.
 * This is a factory so the component controls when the connection is made
 * and which session_id is used, rather than doing it at module load time.
 */
export function createSocket(sessionId: string): Socket {
  return io(FLASK_URL, {
    query: { sessionId },
    autoConnect: false,
    transports: ['websocket'],
  })
}
