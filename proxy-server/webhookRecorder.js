// Records every /webhooks/** request the gateway sees, including requests
// Flask never answered (proxy errors, client aborts), into Redis:
//
//   LPUSH + LTRIM  slbp:email:webhook_hits        (newest first, last 500)
//   PUBLISH        slbp:email:webhook_hits:live   (Flask relays to socket.io)
//
// Recording is best effort and never affects the proxied response. Flask
// annotates its verdict in a private response header that is stripped here
// before the reply reaches the caller.

const crypto = require("crypto");
const { createClient } = require("redis");

const HITS_KEY = "slbp:email:webhook_hits";
const LIVE_CHANNEL = "slbp:email:webhook_hits:live";
const MAX_HITS = 500;
const OUTCOME_HEADER = "x-slbp-webhook-outcome";

const REDIS_HOST = process.env.REDIS_HOST || "127.0.0.1";
const REDIS_PORT = parseInt(process.env.REDIS_PORT || "0", 10);

let client = null;
// Records produced while Redis is unreachable; flushed on reconnect.
const unsent = [];

function connectRedis() {
  if (!REDIS_PORT) {
    console.warn("[proxy] REDIS_PORT not set; webhook hits are not recorded");
    return;
  }
  client = createClient({
    socket: {
      host: REDIS_HOST,
      port: REDIS_PORT,
      reconnectStrategy: (retries) => Math.min(retries * 500, 5000),
    },
    // Fail fast instead of queueing unboundedly while disconnected.
    disableOfflineQueue: true,
  });
  client.on("error", (err) => {
    console.error("[proxy] webhook recorder Redis error:", err.message);
  });
  client.on("ready", () => {
    while (unsent.length > 0) write(unsent.shift());
  });
  client.connect().catch((err) => {
    console.error(
      "[proxy] webhook recorder Redis connect failed:",
      err.message,
    );
  });
}

function write(record) {
  const payload = JSON.stringify(record);
  if (!client || !client.isReady) {
    unsent.push(record);
    if (unsent.length > MAX_HITS) unsent.shift();
    return;
  }
  client
    .multi()
    .lPush(HITS_KEY, payload)
    .lTrim(HITS_KEY, 0, MAX_HITS - 1)
    .publish(LIVE_CHANNEL, payload)
    .exec()
    .catch((err) => {
      console.error("[proxy] webhook hit not recorded:", err.message);
    });
}

function parseOutcome(raw) {
  if (!raw) return null;
  try {
    return JSON.parse(Array.isArray(raw) ? raw[0] : raw);
  } catch {
    return { result: "unparseable-outcome-header" };
  }
}

function remoteIp(req) {
  const forwarded = req.headers["x-forwarded-for"];
  if (forwarded) return String(forwarded).split(",")[0].trim();
  return req.socket.remoteAddress || null;
}

// Express middleware: mount before the /webhooks proxy.
function recordWebhookHits(req, res, next) {
  const started = Date.now();
  const hit = {
    id: crypto.randomUUID(),
    received_at_ms: started,
    method: req.method,
    // Path only: query strings may carry push verification tokens.
    path: req.originalUrl.split("?")[0],
    remote_ip: remoteIp(req),
    user_agent: req.headers["user-agent"] || null,
    content_length: req.headers["content-length"]
      ? Number(req.headers["content-length"])
      : null,
    has_authorization: Boolean(req.headers.authorization),
    status: null,
    duration_ms: null,
    stage: "pending",
    proxy_error: null,
    flask: null,
  };
  req.webhookHit = hit;
  res.on("close", () => {
    hit.duration_ms = Date.now() - started;
    if (res.writableFinished) {
      hit.status = res.statusCode;
      if (hit.stage === "pending") hit.stage = "answered";
    } else {
      hit.stage = "client_aborted";
      hit.status = res.headersSent ? res.statusCode : null;
    }
    write(hit);
  });
  next();
}

// http-proxy-middleware `on` handlers for the /webhooks proxy.
const webhookProxyEvents = {
  proxyRes(proxyRes, req) {
    const hit = req.webhookHit;
    const raw = proxyRes.headers[OUTCOME_HEADER];
    // http-proxy copies headers after this event, so the delete is effective.
    delete proxyRes.headers[OUTCOME_HEADER];
    if (hit) {
      hit.stage = "answered";
      hit.flask = parseOutcome(raw);
    }
  },
  // NOTE: supplying `on.error` disables http-proxy-middleware's default
  // error-response plugin, so this handler MUST answer the request itself or
  // the caller hangs.
  error(err, req, res) {
    const hit = req.webhookHit;
    if (hit) {
      hit.stage = "proxy_error";
      // Dual-stack connects fail with an AggregateError whose own message is
      // empty; surface the per-address errors instead.
      const detail =
        err.message ||
        (Array.isArray(err.errors)
          ? err.errors.map((inner) => inner.message).join("; ")
          : "");
      hit.proxy_error = `${err.code || "ERROR"}: ${detail}`;
    }
    if (res && typeof res.writeHead === "function") {
      if (!res.headersSent) {
        res.writeHead(err.code === "ETIMEDOUT" ? 504 : 502, {
          "Content-Type": "text/plain",
        });
      }
      res.end("Bad gateway: webhook backend unavailable");
    } else if (res && typeof res.destroy === "function") {
      res.destroy();
    }
  },
};

module.exports = { connectRedis, recordWebhookHits, webhookProxyEvents };
