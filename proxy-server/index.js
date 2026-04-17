const express = require('express');
const httpProxy = require('http-proxy');
const { createProxyMiddleware } = require('http-proxy-middleware');

const PROXY_PORT   = parseInt(process.env.PROXY_PORT   || '0', 10);
const FLASK_PORT   = process.env.FLASK_PORT   || '5000';
const UI_PORT      = process.env.UI_PORT      || '5173';
const LOGGING_PORT = process.env.LOGGING_PORT || '8080';

const FLASK_ORIGIN   = `http://localhost:${FLASK_PORT}`;
const UI_ORIGIN      = `http://localhost:${UI_PORT}`;
const LOGGING_ORIGIN = `http://localhost:${LOGGING_PORT}`;

const app = express();

// Must be declared before proxy middleware so Express handles it directly.
app.get('/runtime-config.js', (_req, res) => {
  res.setHeader('Content-Type', 'application/javascript');
  res.setHeader('Cache-Control', 'no-store');
  res.end(`window.__GATEWAY_URL__ = ${JSON.stringify(`http://localhost:${PROXY_PORT}`)};`);
});

// /api/** → Flask (REST only; WebSocket upgrades handled separately below).
// Mounted at root with pathFilter so Express does NOT strip the /api prefix —
// Flask needs to receive the full path (e.g. /api/sessions, /api/socket.io).
app.use(createProxyMiddleware({
  pathFilter: '/api',
  target: FLASK_ORIGIN,
  changeOrigin: true,
}));

// /logging/** → Logging server. Strip /logging prefix before forwarding.
app.use(createProxyMiddleware({
  pathFilter: '/logging',
  target: LOGGING_ORIGIN,
  changeOrigin: true,
  pathRewrite: { '^/logging': '' },
}));

// Everything else → UI static server.
app.use(createProxyMiddleware({
  target: UI_ORIGIN,
  changeOrigin: true,
}));

const server = app.listen(PROXY_PORT, () => {
  const port = server.address().port;
  console.log(`[proxy] Gateway listening on http://localhost:${port}`);
  console.log(`[proxy] /api/**     → ${FLASK_ORIGIN}`);
  console.log(`[proxy] /logging/** → ${LOGGING_ORIGIN}`);
  console.log(`[proxy] /**         → ${UI_ORIGIN}`);
});

// WebSocket upgrade handling — bypasses Express entirely.
// http-proxy-middleware v3 does not expose an .upgrade method, so we use
// http-proxy directly, which is the reliable underlying library for this.
const wsProxy = httpProxy.createProxyServer({ target: FLASK_ORIGIN, ws: true, changeOrigin: true });

wsProxy.on('error', (err, _req, socket) => {
  console.error('[proxy] WS error:', err.message);
  socket.destroy();
});

server.on('upgrade', (req, socket, head) => {
  if (req.url.startsWith('/api/')) {
    wsProxy.ws(req, socket, head);
  } else {
    socket.destroy();
  }
});
