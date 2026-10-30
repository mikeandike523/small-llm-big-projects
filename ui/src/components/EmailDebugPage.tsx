/** @jsxImportSource @emotion/react */
import { css } from "@emotion/react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

type EmailState = {
  last_processed_history_id: string | null;
  watch_last_success_unix: number | null;
  watch_expiration_ms: number | null;
  watch_last_error: string | null;
  sync_last_success_unix: number | null;
  sync_last_error: string | null;
};

type EmailStatus = {
  enabled: boolean;
  mailbox_email?: string;
  alias_email?: string;
  pending_notifications?: number;
  session_integration: string;
  state?: EmailState;
};

type EmailMessage = {
  gmail_message_id: string;
  internal_date_ms: number;
  direction: "inbound" | "outbound";
  subject_text: string;
  from_header: string;
  to_header: string;
  cc_header: string;
  snippet: string;
  text_body: string;
  html_body: string;
  labels: string[];
  attachments: Array<{ filename: string; mime_type: string; size: number }>;
  relevant_to_alias: boolean;
  alias_match_reason: string | null;
};

type EmailThread = {
  thread_id: string;
  latest_internal_date_ms: number;
  messages: EmailMessage[];
  session_integration: string;
};

const pageCss = css`
  min-height: 100%;
  background: #0f0f0f;
  color: #dce5f5;
  font-family: "Fira Code", "Consolas", monospace;
`;
const headerCss = css`
  position: sticky;
  top: 0;
  z-index: 2;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 18px 28px;
  background: rgba(15, 15, 15, 0.96);
  border-bottom: 1px solid #283149;
`;
const titleCss = css`
  font-size: 18px;
  letter-spacing: 2px;
  text-transform: uppercase;
`;
const buttonCss = css`
  background: #171b25;
  border: 1px solid #3e4d70;
  border-radius: 5px;
  color: #cbd8ef;
  padding: 7px 12px;
  font: inherit;
  font-size: 12px;
  cursor: pointer;
  &:hover {
    border-color: #7290ca;
  }
`;
const mainCss = css`
  width: min(1180px, calc(100% - 40px));
  margin: 0 auto;
  padding: 24px 0 60px;
`;
const panelCss = css`
  border: 1px solid #293450;
  border-radius: 8px;
  background: #141720;
  padding: 16px;
  margin-bottom: 18px;
`;
const statusGridCss = css`
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 12px;
`;
const labelCss = css`
  color: #7888a8;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-bottom: 4px;
`;
const valueCss = css`
  overflow-wrap: anywhere;
  font-size: 12px;
`;
const errorCss = css`
  margin-top: 12px;
  padding: 10px;
  color: #ffb4b4;
  background: #2b161a;
  border: 1px solid #74323c;
  border-radius: 5px;
  white-space: pre-wrap;
`;
const threadCss = css`
  border: 1px solid #303b56;
  border-radius: 9px;
  background: #12151d;
  margin-bottom: 14px;
  overflow: hidden;
`;
const threadSummaryCss = css`
  cursor: pointer;
  padding: 15px 18px;
  list-style: none;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 14px;
  &::-webkit-details-marker {
    display: none;
  }
`;
const subjectCss = css`
  color: #f3f6fc;
  font-size: 14px;
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;
const mutedCss = css`
  color: #8190aa;
  font-size: 11px;
  margin-top: 5px;
`;
const messageCss = css`
  margin: 0 14px 14px;
  padding: 14px;
  border: 1px solid #2a3550;
  border-left: 3px solid #6387db;
  border-radius: 6px;
  background: #171b25;
`;
const outboundCss = css`
  border-left-color: #54a17e;
`;
const badgeCss = css`
  display: inline-block;
  margin-right: 7px;
  padding: 2px 6px;
  border-radius: 10px;
  background: #263451;
  color: #b9cdf6;
  font-size: 9px;
  text-transform: uppercase;
`;
const headerRowsCss = css`
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr);
  gap: 4px 10px;
  margin: 10px 0;
  font-size: 11px;
  div:nth-of-type(odd) {
    color: #71809d;
  }
  div:nth-of-type(even) {
    overflow-wrap: anywhere;
  }
`;
const bodyCss = css`
  margin-top: 12px;
  padding: 12px;
  max-height: 600px;
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  background: #0e1118;
  border-radius: 5px;
  color: #dce3ef;
  font:
    12px/1.55 "Fira Code",
    "Consolas",
    monospace;
`;

function time(value?: number | null, milliseconds = false) {
  if (!value) return "never";
  return new Date(milliseconds ? value : value * 1000).toLocaleString();
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div css={labelCss}>{label}</div>
      <div css={valueCss}>{value}</div>
    </div>
  );
}

export default function EmailDebugPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<EmailStatus | null>(null);
  const [threads, setThreads] = useState<EmailThread[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const statusResponse = await fetch("/api/email/status");
      if (!statusResponse.ok)
        throw new Error(`Status request failed (${statusResponse.status})`);
      const nextStatus: EmailStatus = await statusResponse.json();
      setStatus(nextStatus);
      if (nextStatus.enabled) {
        const threadResponse = await fetch("/api/email/threads?limit=50");
        if (!threadResponse.ok)
          throw new Error(`Thread request failed (${threadResponse.status})`);
        const body: { threads: EmailThread[] } = await threadResponse.json();
        setThreads(body.threads);
      } else {
        setThreads([]);
      }
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  return (
    <div css={pageCss}>
      <header css={headerCss}>
        <div>
          <div css={titleCss}>Email Debug</div>
          <div css={mutedCss}>
            Gmail watch, sync, and complete thread inspection
          </div>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button css={buttonCss} onClick={() => void refresh()}>
            Refresh
          </button>
          <button css={buttonCss} onClick={() => navigate("/")}>
            ← Dashboard
          </button>
        </div>
      </header>
      <main css={mainCss}>
        <section css={panelCss}>
          <div css={statusGridCss}>
            <Field
              label="Channel"
              value={status?.enabled ? "enabled" : "disabled"}
            />
            <Field label="Mailbox" value={status?.mailbox_email ?? "—"} />
            <Field label="Alias" value={status?.alias_email ?? "—"} />
            <Field
              label="History cursor"
              value={status?.state?.last_processed_history_id ?? "—"}
            />
            <Field
              label="Pending pushes"
              value={status?.pending_notifications ?? 0}
            />
            <Field
              label="Watch renewed"
              value={time(status?.state?.watch_last_success_unix)}
            />
            <Field
              label="Watch expires"
              value={time(status?.state?.watch_expiration_ms, true)}
            />
            <Field
              label="Last sync"
              value={time(status?.state?.sync_last_success_unix)}
            />
            <Field
              label="Session routing"
              value="stubbed — no session activity"
            />
          </div>
          {status?.state?.watch_last_error && (
            <div css={errorCss}>Watch: {status.state.watch_last_error}</div>
          )}
          {status?.state?.sync_last_error && (
            <div css={errorCss}>Sync: {status.state.sync_last_error}</div>
          )}
          {error && <div css={errorCss}>{error}</div>}
        </section>

        {threads.length === 0 && (
          <div css={panelCss}>No captured email threads yet.</div>
        )}
        {threads.map((thread) => {
          const latest = thread.messages[thread.messages.length - 1];
          return (
            <details css={threadCss} key={thread.thread_id} open>
              <summary css={threadSummaryCss}>
                <div>
                  <div css={subjectCss}>
                    {latest?.subject_text || "(no subject)"}
                  </div>
                  <div css={mutedCss}>
                    {thread.messages.length} message(s) · thread{" "}
                    {thread.thread_id}
                  </div>
                </div>
                <div css={mutedCss}>
                  {time(thread.latest_internal_date_ms, true)}
                </div>
              </summary>
              {thread.messages.map((message) => (
                <article
                  css={[
                    messageCss,
                    message.direction === "outbound" && outboundCss,
                  ]}
                  key={message.gmail_message_id}
                >
                  <div>
                    <span css={badgeCss}>{message.direction}</span>
                    {message.relevant_to_alias && (
                      <span css={badgeCss}>
                        alias: {message.alias_match_reason}
                      </span>
                    )}
                    <span css={mutedCss}>
                      {time(message.internal_date_ms, true)}
                    </span>
                  </div>
                  <div css={headerRowsCss}>
                    <div>From</div>
                    <div>{message.from_header || "—"}</div>
                    <div>To</div>
                    <div>{message.to_header || "—"}</div>
                    <div>Cc</div>
                    <div>{message.cc_header || "—"}</div>
                  </div>
                  {message.attachments.length > 0 && (
                    <div css={mutedCss}>
                      Attachments:{" "}
                      {message.attachments
                        .map(
                          (item) =>
                            `${item.filename || "unnamed"} (${item.mime_type}, ${item.size} bytes)`,
                        )
                        .join(", ")}
                    </div>
                  )}
                  <pre css={bodyCss}>
                    {message.text_body || message.snippet || "(empty body)"}
                  </pre>
                </article>
              ))}
            </details>
          );
        })}
      </main>
    </div>
  );
}
