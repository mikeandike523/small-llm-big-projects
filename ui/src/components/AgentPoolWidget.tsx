/** @jsxImportSource @emotion/react */
import { css } from "@emotion/react";
import type { AgentPoolSession, AgentSummary } from "../types";

interface Props {
  agent: AgentSummary;
  onOpenSession: (sessionId: string) => void;
  onDeleteSession: (session: AgentPoolSession) => void;
  onOpenSettings: () => void;
}

const STATUS_STYLES: Record<
  AgentPoolSession["status"],
  { color: string; label: string }
> = {
  idle: { color: "#3a3a3a", label: "Idle" },
  running: { color: "#44cc77", label: "Turn in progress" },
  waiting_approval: { color: "#e0a030", label: "Waiting for approval" },
  queued: { color: "#7fb2e6", label: "Email queued" },
  failed: { color: "#e05555", label: "Latest email failed" },
  cancelled: { color: "#888", label: "Latest email was cancelled" },
  interrupted: { color: "#c08050", label: "Latest email was interrupted" },
};

const widgetCss = css`
  border: 1px solid #1e1e2c;
  border-radius: 8px;
  background: #101018;
  margin-bottom: 16px;
  font-family: "Fira Code", "Consolas", monospace;
`;

const headerCss = css`
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  font-size: 12px;
  color: #dbe5ff;
`;

const mutedCss = css`
  color: #7a86a8;
`;

const settingsBtnCss = css`
  margin-left: auto;
  background: none;
  border: 1px solid #2a3a6e;
  border-radius: 4px;
  color: #8aacff;
  font-family: inherit;
  font-size: 11px;
  padding: 3px 9px;
  cursor: pointer;
`;

const rowCss = css`
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 7px 14px;
  border-top: 1px solid #191924;
  font-size: 11px;
  color: #c0c8dc;
  cursor: pointer;
  &:hover {
    background: #161622;
  }
`;

const dotCss = (color: string) => css`
  flex: none;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: ${color};
`;

const senderCss = css`
  flex: 0 1 34%;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

const threadCss = css`
  flex: none;
  color: #7a86a8;
`;

const subjectCss = css`
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

const deleteBtnCss = css`
  flex: none;
  background: none;
  border: none;
  color: #7a6a6a;
  font-family: inherit;
  font-size: 11px;
  cursor: pointer;
  &:hover:not(:disabled) {
    color: #cc6666;
  }
  &:disabled {
    cursor: not-allowed;
    opacity: 0.4;
  }
`;

const emptyCss = css`
  padding: 8px 14px 12px;
  font-size: 11px;
  color: #7a86a8;
`;

function senderLabel(session: AgentPoolSession): string {
  return session.display_name
    ? `${session.display_name} <${session.sender_address}>`
    : session.sender_address;
}

export default function AgentPoolWidget({
  agent,
  onOpenSession,
  onDeleteSession,
  onOpenSettings,
}: Props) {
  return (
    <div css={widgetCss}>
      <div css={headerCss}>
        {agent.name ? (
          <span>
            {agent.name} <span css={mutedCss}>&lt;{agent.email}&gt;</span>
          </span>
        ) : (
          <span css={mutedCss}>Unregistered agent ({agent.slug})</span>
        )}
        {agent.email !== null && !agent.enabled && (
          <span css={mutedCss}>disabled</span>
        )}
        <button css={settingsBtnCss} onClick={onOpenSettings}>
          Settings
        </button>
      </div>
      {agent.sessions.length === 0 && (
        <div css={emptyCss}>No conversations yet.</div>
      )}
      {agent.sessions.map((session) => {
        const status = STATUS_STYLES[session.status];
        const active =
          session.status === "running" || session.status === "waiting_approval";
        return (
          <div
            key={session.session_id}
            css={rowCss}
            role="button"
            tabIndex={0}
            onClick={() => onOpenSession(session.session_id)}
            onKeyDown={(e) => {
              if (e.key === "Enter") onOpenSession(session.session_id);
            }}
          >
            <span
              css={dotCss(status.color)}
              title={status.label}
              aria-label={status.label}
            />
            <span css={senderCss} title={senderLabel(session)}>
              {senderLabel(session)}
            </span>
            <span css={threadCss} title={session.gmail_thread_id}>
              thread {session.gmail_thread_id.slice(0, 10)}
            </span>
            <span css={subjectCss} title={session.subject}>
              {session.subject || "(no subject)"}
            </span>
            <button
              css={deleteBtnCss}
              disabled={active}
              title={
                active
                  ? "Stop this session's turn before deleting it"
                  : "Delete this session"
              }
              onClick={(e) => {
                e.stopPropagation();
                onDeleteSession(session);
              }}
            >
              delete
            </button>
          </div>
        );
      })}
    </div>
  );
}
