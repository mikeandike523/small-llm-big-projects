/** @jsxImportSource @emotion/react */
import { css } from "@emotion/react";
import { useCallback, useEffect, useState } from "react";
import { createSocket } from "../socket";

// Recorded by the gateway proxy (proxy-server/webhookRecorder.js) for every
// /webhooks/** request, including ones Flask never answered.
export type WebhookHit = {
  id: string;
  received_at_ms: number;
  method: string;
  path: string;
  remote_ip: string | null;
  user_agent: string | null;
  content_length: number | null;
  has_authorization: boolean;
  status: number | null;
  duration_ms: number | null;
  stage: "answered" | "proxy_error" | "client_aborted" | "pending";
  proxy_error: string | null;
  flask: {
    result: string;
    reason?: string | null;
    pubsub_message_id?: string;
    history_id?: string;
  } | null;
};

const MAX_HITS = 500;
const ROOM_JOIN_EVENT = "email_webhook_debug_join";
const HIT_EVENT = "email_webhook_hit";

const asideCss = css`
  position: sticky;
  top: 86px;
  align-self: start;
  max-height: calc(100vh - 110px);
  display: flex;
  flex-direction: column;
  border: 1px solid #293450;
  border-radius: 8px;
  background: #141720;
  overflow: hidden;
  @media (max-width: 900px) {
    position: static;
    max-height: 420px;
  }
`;
const asideHeaderCss = css`
  padding: 12px 14px;
  border-bottom: 1px solid #293450;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 1px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
`;
const liveCss = (live: boolean) => css`
  font-size: 10px;
  letter-spacing: 0;
  text-transform: none;
  color: ${live ? "#7fd4a4" : "#e0a35a"};
`;
const listCss = css`
  overflow-y: auto;
  flex: 1;
`;
const rowCss = css`
  border-bottom: 1px solid #1f2638;
  font-size: 11px;
  summary {
    cursor: pointer;
    padding: 8px 12px;
    list-style: none;
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto;
    gap: 4px 8px;
    align-items: center;
  }
  summary::-webkit-details-marker {
    display: none;
  }
  &[open] summary {
    background: #191e2b;
  }
`;
const statusCss = (color: string) => css`
  min-width: 38px;
  text-align: center;
  padding: 2px 5px;
  border-radius: 4px;
  font-weight: 700;
  color: #0f0f0f;
  background: ${color};
`;
const reasonCss = css`
  grid-column: 2 / 4;
  color: #8f9cb8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;
const detailCss = css`
  margin: 0;
  padding: 8px 12px 10px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  color: #c6d2e8;
  background: #10131b;
  font-size: 10px;
`;
const emptyCss = css`
  padding: 14px;
  color: #8190aa;
  font-size: 11px;
`;

function statusColor(hit: WebhookHit): string {
  if (hit.stage === "proxy_error") return "#ff7b7b";
  if (hit.stage === "client_aborted" || hit.status === null) return "#8a93a6";
  if (hit.status < 300) return "#7fd4a4";
  if (hit.status < 500) return "#e8c06a";
  return "#ff7b7b";
}

function statusLabel(hit: WebhookHit): string {
  if (hit.stage === "client_aborted")
    return hit.status ? `${hit.status}✕` : "✕";
  return hit.status === null ? "…" : String(hit.status);
}

function verdict(hit: WebhookHit): string {
  if (hit.stage === "proxy_error")
    return `proxy error (Flask unreachable): ${hit.proxy_error}`;
  if (hit.stage === "client_aborted")
    return "caller disconnected before a response";
  if (!hit.flask) return "no Flask verdict (non-email route or crash)";
  const reason = hit.flask.reason ? `: ${hit.flask.reason}` : "";
  const history = hit.flask.history_id
    ? ` history=${hit.flask.history_id}`
    : "";
  return `${hit.flask.result}${reason}${history}`;
}

function mergeHits(
  current: WebhookHit[],
  incoming: WebhookHit[],
): WebhookHit[] {
  const byId = new Map<string, WebhookHit>();
  for (const hit of [...incoming, ...current]) {
    if (!byId.has(hit.id)) byId.set(hit.id, hit);
  }
  return [...byId.values()]
    .sort((a, b) => b.received_at_ms - a.received_at_ms)
    .slice(0, MAX_HITS);
}

export default function EmailWebhookHitsPanel() {
  const [hits, setHits] = useState<WebhookHit[]>([]);
  const [live, setLive] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadHistory = useCallback(async () => {
    try {
      const response = await fetch(`/api/email/webhook-hits?limit=${MAX_HITS}`);
      if (!response.ok)
        throw new Error(`Webhook log request failed (${response.status})`);
      const body: { hits: WebhookHit[] } = await response.json();
      setHits((current) => mergeHits(current, body.hits));
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, []);

  useEffect(() => {
    const socket = createSocket();
    const onConnect = () => {
      // Rooms do not survive a reconnect: re-join, then backfill anything
      // recorded while we were disconnected (e.g. proxy errors while Flask
      // was down).
      socket.emit(ROOM_JOIN_EVENT, {}, () => setLive(true));
      void loadHistory();
    };
    const onDisconnect = () => setLive(false);
    const onHit = (hit: WebhookHit) =>
      setHits((current) => mergeHits(current, [hit]));
    socket.on("connect", onConnect);
    socket.on("disconnect", onDisconnect);
    socket.on("connect_error", onDisconnect);
    socket.on(HIT_EVENT, onHit);
    socket.connect();
    void loadHistory();
    return () => {
      socket.off("connect", onConnect);
      socket.off("disconnect", onDisconnect);
      socket.off("connect_error", onDisconnect);
      socket.off(HIT_EVENT, onHit);
      socket.disconnect();
    };
  }, [loadHistory]);

  return (
    <aside css={asideCss}>
      <div css={asideHeaderCss}>
        <span>Webhook hits ({hits.length})</span>
        <span css={liveCss(live)}>
          {live ? "● live" : "○ disconnected — reconnecting"}
        </span>
      </div>
      {error && <div css={emptyCss}>{error}</div>}
      <div css={listCss}>
        {hits.length === 0 && (
          <div css={emptyCss}>
            No /webhooks requests recorded yet. The proxy keeps the last{" "}
            {MAX_HITS} in Redis.
          </div>
        )}
        {hits.map((hit) => (
          <details css={rowCss} key={hit.id}>
            <summary>
              <span css={statusCss(statusColor(hit))}>{statusLabel(hit)}</span>
              <span>
                {hit.method} {hit.path}
              </span>
              <span
                title={new Date(hit.received_at_ms).toLocaleString()}
                style={{ color: "#8190aa" }}
              >
                {new Date(hit.received_at_ms).toLocaleTimeString()}
              </span>
              <span css={reasonCss}>
                {verdict(hit)}
                {hit.duration_ms !== null ? ` · ${hit.duration_ms}ms` : ""}
              </span>
            </summary>
            <pre css={detailCss}>{JSON.stringify(hit, null, 2)}</pre>
          </details>
        ))}
      </div>
    </aside>
  );
}
