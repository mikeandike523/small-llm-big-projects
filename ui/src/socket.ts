import { io } from 'socket.io-client'

const FLASK_URL = import.meta.env.VITE_FLASK_URL ?? 'http://localhost:5000'

function initSessionId(): string {
  let id = sessionStorage.getItem('session_id')
  if (!id) {
    id = crypto.randomUUID()
    sessionStorage.setItem('session_id', id)
  }
  return id
}

export const SESSION_ID = initSessionId()

export const socket = io(FLASK_URL, {
  query: { sessionId: SESSION_ID },
  autoConnect: true,
  transports: ['websocket'],
})
