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

// Inject runtime config so the frontend discovers the gateway URL.
app.get('/runtime-config.js', (_req, res) => {
  res.setHeader('Content-Type', 'application/javascript');
  res.setHeader('Cache-Control', 'no-store');
  res.end(`window.__GATEWAY_URL__ = ${JSON.stringify(`http://localhost:${PROXY_PORT}`)};`);
});

// /api/** → Flask (REST + Socket.IO WebSocket upgrade)
const apiProxy = createProxyMiddleware({
  target: FLASK_ORIGIN,
  changeOrigin: true,
  ws: true,
});
app.use('/api', apiProxy);

// /logging/** → Logging server (strip /logging prefix)
app.use('/logging', createProxyMiddleware({
  target: LOGGING_ORIGIN,
  changeOrigin: true,
  pathRewrite: { '^/logging': '' },
}));

// Everything else → UI static server
app.use('/', createProxyMiddleware({
  target: UI_ORIGIN,
  changeOrigin: true,
}));

const server = app.listen(PROXY_PORT, () => {
  const port = server.address().port;
  console.log(`[proxy] Gateway listening on http://localhost:${port}`);
  console.log(`[proxy] /api/** → ${FLASK_ORIGIN}`);
  console.log(`[proxy] /logging/** → ${LOGGING_ORIGIN}`);
  console.log(`[proxy] /** → ${UI_ORIGIN}`);
});

// WebSocket upgrade must be wired to the api proxy explicitly.
server.on('upgrade', apiProxy.upgrade);
