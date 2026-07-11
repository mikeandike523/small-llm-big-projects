import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import type { Server } from 'node:http';

export interface OpenPayload {
  sessionId?: string;
  dashboard?: boolean;
  proxyOrigin: string;
}

export interface ControlServerHandle {
  server: Server;
  cleanup: () => void;
}

/**
 * Tiny local HTTP server the CLI talks to instead of relying on OS process
 * enumeration: GET /health tells the CLI the app is alive and ready, POST /open
 * tells it to focus a tab. The assigned port is written to .slbp-app-server.json
 * at the repo root (mirrors .slbp-server.json's pattern for the backend ports),
 * and removed again on quit so a future health-check correctly reports "not running".
 */
export function startControlServer(
  repoRoot: string,
  onOpen: (payload: OpenPayload) => void,
): ControlServerHandle {
  const stateFile = path.join(repoRoot, '.slbp-app-server.json');

  const server = http.createServer((req, res) => {
    if (req.method === 'GET' && req.url === '/health') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ status: 'ok', pid: process.pid }));
      return;
    }

    if (req.method === 'POST' && req.url === '/open') {
      let body = '';
      req.on('data', (chunk) => {
        body += chunk;
      });
      req.on('end', () => {
        try {
          const payload = JSON.parse(body || '{}') as OpenPayload;
          if (!payload.proxyOrigin) {
            throw new Error('proxyOrigin is required');
          }
          onOpen(payload);
          res.writeHead(200, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ status: 'ok' }));
        } catch (err) {
          res.writeHead(400, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ status: 'error', message: String(err) }));
        }
      });
      return;
    }

    res.writeHead(404);
    res.end();
  });

  server.listen(0, '127.0.0.1', () => {
    const address = server.address();
    const port = typeof address === 'object' && address ? address.port : 0;
    fs.writeFileSync(
      stateFile,
      JSON.stringify({ port, pid: process.pid }, null, 2),
    );
  });

  const cleanup = () => {
    try {
      fs.unlinkSync(stateFile);
    } catch {
      // already gone
    }
  };

  return { server, cleanup };
}
