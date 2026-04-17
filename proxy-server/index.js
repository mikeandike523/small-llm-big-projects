const express = require('express');
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

// /api/** → Flask (REST + Socket.IO WebSocket upgrade).
// Mounted at root with pathFilter so Express does NOT strip the /api prefix —
// Flask needs to receive the full path (e.g. /api/sessions, /api/socket.io).
const apiProxy = createProxyMiddleware({
  pathFilter: '/api',
  target: FLASK_ORIGIN,
  changeOrigin: true,
  ws: true,
});
app.use(apiProxy);

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

// Wire WebSocket upgrades to the api proxy (bypasses Express routing).
server.on('upgrade', apiProxy.upgrade);
