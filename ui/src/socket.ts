import { io, type Socket } from "socket.io-client";

export function createSocket(sessionId?: string): Socket {
  const query: Record<string, string> = {};
  if (sessionId) query.sessionId = sessionId;
  return io(window.location.origin, {
    path: "/api/socket.io",
    query: Object.keys(query).length > 0 ? query : undefined,
    autoConnect: false,
    transports: ["websocket"],
  });
}
