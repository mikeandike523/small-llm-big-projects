const express = require("express");
const httpProxy = require("http-proxy");
const { createProxyMiddleware } = require("http-proxy-middleware");
const {
  connectRedis,
  recordWebhookHits,
  webhookProxyEvents,
} = require("./webhookRecorder");

const PROXY_PORT = parseInt(process.env.PROXY_PORT || "0", 10);
const FLASK_PORT = process.env.FLASK_PORT || "5000";
const UI_PORT = process.env.UI_PORT || "5173";
const ARTIFACT_PORT = process.env.ARTIFACT_PORT || "0";
const ARTIFACT_HOST = (process.env.ARTIFACT_HOST || "artifact.localhost").toLowerCase().replace(/^\.+|\.+$/g, "");

const FLASK_ORIGIN = `http://localhost:${FLASK_PORT}`;
const UI_ORIGIN = `http://localhost:${UI_PORT}`;

const app = express();

// Wildcard artifact hosts are routed before the normal UI fallback. The
// artifact service validates the complete host/id again; this rule only keeps
// artifact traffic out of the UI server.
app.use(
  createProxyMiddleware({
    pathFilter: (_path, req) => {
      const host = String(req.headers.host || "").split(":")[0].toLowerCase();
      return host.endsWith(`.${ARTIFACT_HOST}`);
    },
    target: `http://127.0.0.1:${ARTIFACT_PORT}`,
    changeOrigin: false,
  }),
);

// /api/** -> Flask (REST only; WebSocket upgrades handled separately below).
// Mounted at root with pathFilter so Express does not strip the /api prefix.
app.use(
  createProxyMiddleware({
    pathFilter: "/api",
    target: FLASK_ORIGIN,
    changeOrigin: true,
  }),
);

// Public Google push endpoints bypass the UI server. Authentication is
// performed by the Flask route using Google-signed OIDC tokens. Every hit,
// including ones Flask never answered, is recorded for the email debug page.
connectRedis();
app.use("/webhooks", recordWebhookHits);
app.use(
  createProxyMiddleware({
    pathFilter: "/webhooks",
    target: FLASK_ORIGIN,
    changeOrigin: true,
    proxyTimeout: 30000,
    on: webhookProxyEvents,
  }),
);

// Everything else -> UI static server.
app.use(
  createProxyMiddleware({
    target: UI_ORIGIN,
    changeOrigin: true,
  }),
);

const server = app.listen(PROXY_PORT, () => {
  const port = server.address().port;
  console.log(`[proxy] Gateway listening on http://localhost:${port}`);
  console.log(`[proxy] /api/** -> ${FLASK_ORIGIN}`);
  console.log(`[proxy] /webhooks/** -> ${FLASK_ORIGIN}`);
  console.log(`[proxy] /** -> ${UI_ORIGIN}`);
});

// WebSocket upgrade handling bypasses Express entirely.
const wsProxy = httpProxy.createProxyServer({
  target: FLASK_ORIGIN,
  ws: true,
  changeOrigin: true,
});

wsProxy.on("error", (err, _req, socket) => {
  console.error("[proxy] WS error:", err.message);
  socket.destroy();
});

server.on("upgrade", (req, socket, head) => {
  if (req.url.startsWith("/api/")) {
    wsProxy.ws(req, socket, head);
  } else {
    socket.destroy();
  }
});
