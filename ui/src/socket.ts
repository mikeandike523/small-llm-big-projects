import { io } from 'socket.io-client'

const FLASK_URL = import.meta.env.VITE_FLASK_URL ?? 'http://localhost:5000'

export const socket = io(FLASK_URL, {
  autoConnect: true,
  transports: ['websocket'],
})
