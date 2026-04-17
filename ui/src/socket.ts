import { io, type Socket } from 'socket.io-client'

// Runtime config injected by serve.cjs via /runtime-config.js takes priority,
// then the Vite build-time env var, then a sensible default.
declare global {
  interface Window {
    __GATEWAY_URL__?: string
  }
}

const GATEWAY_URL =
  (typeof window !== 'undefined' && window.__GATEWAY_URL__)
    ? window.__GATEWAY_URL__
    : (import.meta.env.VITE_GATEWAY_URL ?? (typeof window !== 'undefined' ? window.location.origin : 'http://localhost:5000'))

export function createSocket(sessionId: string): Socket {
  return io(GATEWAY_URL, {
    path: '/api/socket.io',
    query: { sessionId },
    autoConnect: false,
    transports: ['websocket'],
  })
}
