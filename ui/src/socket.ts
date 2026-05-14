import { io, type Socket } from "socket.io-client";

export function createSocket(sessionId: string): Socket {
  return io(window.location.origin, {
    path: "/api/socket.io",
    query: { sessionId },
    autoConnect: false,
    transports: ["websocket"],
  });
}
