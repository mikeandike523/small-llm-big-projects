import { useState, useEffect } from "react";
import { ApprovalItem } from "../types";
import { css } from "@emotion/react";
import JsonArgsViewer from "./JsonArgsViewer";
import DiffViewer from "../subcomponents/Chat/DiffViewer";

const approvalResolvedBubbleCss = (approved: boolean) => css`
  font-family: "Consolas", monospace;
  font-size: 12px;
  color: ${approved ? "#4ade80" : "#f87171"};
  padding: 4px 8px;
  border-radius: 4px;
  background: ${approved ? "#0a1a0a" : "#1a0a0a"};
  border: 1px solid ${approved ? "#1a4a1a" : "#4a1a1a"};
  word-break: break-all;
`;

const approvalPendingCardCss = css`
  background: #1a1200;
  border: 1px solid #6a4800;
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
`;

const approvalToolNameCss = css`
  font-family: "Consolas", monospace;
  font-size: 12px;
  color: #d4a030;
  font-weight: 600;
  word-break: break-all;
`;

const approvalArgsCss = css`
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
`;

const approvalArgsAndDiffContainerCss = css`
  display: flex;
  gap: 12px;
`;

const approvalButtonRowCss = css`
  display: flex;
  gap: 6px;
`;

const approveButtonCss = css`
  flex: 1;
  background: #14532d;
  color: #4ade80;
  border: 1px solid #166534;
  border-radius: 5px;
  padding: 5px 0;
  font-size: 12px;
  cursor: pointer;
  font-family: "Consolas", monospace;
  transition: background 0.15s;
  &:hover {
    background: #166534;
  }
`;

const denyButtonCss = css`
  flex: 1;
  background: #450a0a;
  color: #f87171;
  border: 1px solid #7f1d1d;
  border-radius: 5px;
  padding: 5px 0;
  font-size: 12px;
  cursor: pointer;
  font-family: "Consolas", monospace;
  transition: background 0.15s;
  &:hover {
    background: #7f1d1d;
  }
`;

const denyRedirectButtonCss = css`
  flex: 1;
  background: #78350f;
  color: #fbbf24;
  border: 1px solid #92400e;
  border-radius: 5px;
  padding: 5px 0;
  font-size: 12px;
  cursor: pointer;
  font-family: "Consolas", monospace;
  transition: background 0.15s;
  &:hover {
    background: #92400e;
  }
`;

const denyAndStopButtonCss = css`
  flex: 1;
  background: #3b0a0a;
  color: #fca5a5;
  border: 1px solid #991b1b;
  border-radius: 5px;
  padding: 5px 0;
  font-size: 12px;
  cursor: pointer;
  font-family: "Consolas", monospace;
  transition: background 0.15s;
  &:hover {
    background: #7f1d1d;
  }
`;

const diffSpinnerCss = css`
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 4px;
  font-size: 11px;
  color: #888;
  font-family: "Consolas", monospace;
`;

const diffSpinnerDotsCss = css`
  display: inline-block;
  width: 12px;
  height: 12px;
  border: 2px solid #333;
  border-top-color: #888;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
`;

const diffErrorCss = css`
  font-size: 11px;
  color: #888;
  font-family: "Consolas", monospace;
  padding: 4px 0;
`;

const diffLabelCss = css`
  font-size: 10px;
  color: #666;
  font-family: "Consolas", monospace;
  margin-bottom: 4px;
`;

const redirectInputAreaCss = css`
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-top: 6px;
`;

const redirectTextareaCss = css`
  width: 100%;
  box-sizing: border-box;
  background: #0f0a00;
  color: #e8d0a0;
  border: 1px solid #6a4800;
  border-radius: 4px;
  padding: 5px 7px;
  font-size: 12px;
  font-family: "Consolas", monospace;
  resize: vertical;
  outline: none;
  &:focus {
    border-color: #d4a030;
  }
`;

const redirectActionRowCss = css`
  display: flex;
  gap: 5px;
`;

const redirectSendButtonCss = css`
  flex: 1;
  background: #14532d;
  color: #4ade80;
  border: 1px solid #166534;
  border-radius: 4px;
  padding: 4px 0;
  font-size: 12px;
  cursor: pointer;
  font-family: "Consolas", monospace;
  transition: background 0.15s;
  &:hover {
    background: #166534;
  }
  &:disabled {
    opacity: 0.4;
    cursor: default;
  }
`;

const redirectCancelButtonCss = css`
  flex: 1;
  background: #1f1f1f;
  color: #eef3ff;
  border: 1px solid #425272;
  border-radius: 4px;
  padding: 4px 0;
  font-size: 12px;
  cursor: pointer;
  font-family: "Consolas", monospace;
  transition: background 0.15s;
  &:hover {
    background: #34435f;
  }
`;

type DiffStatus = "idle" | "loading" | "loaded" | "error";

// text_editor write actions that support a before/after diff preview. Must
// stay in sync with _WRITE_ACTIONS in src/tools/_text_editor_actions.py.
const TEXT_EDITOR_WRITE_ACTIONS = new Set([
  "apply_patch",
  "search_replace",
  "regex_replace",
  "insert_lines",
  "delete_lines",
  "append_lines",
  "prepend_lines",
  "normalize_eol",
  "convert_indentation",
]);

function getSessionId(): string {
  return (
    new URLSearchParams(window.location.search).get("sessionId") ||
    sessionStorage.getItem("session_id") ||
    ""
  );
}

export default function ToolApprovalBubble({
  item,
  onApprove,
  onDeny,
  onDenyWithRedirect,
  onDenyAndStop,
}: {
  item: ApprovalItem;
  onApprove: (id: string) => void;
  onDeny: (id: string) => void;
  onDenyWithRedirect: (id: string, message: string) => void;
  onDenyAndStop: (id: string) => void;
}) {
  const [showRedirect, setShowRedirect] = useState(false);
  const [redirectText, setRedirectText] = useState("");
  const [diffStatus, setDiffStatus] = useState<DiffStatus>("idle");
  const [diffData, setDiffData] = useState<{ before: string; after: string } | null>(null);

  const isTextEditorWrite =
    item.tool_name === "text_editor" &&
    TEXT_EDITOR_WRITE_ACTIONS.has(item.args.action as string);
  const isWriteTextFile = item.tool_name === "write_text_file";
  const wantsDiffPreview = isTextEditorWrite || isWriteTextFile;

  const diffLabel: string | null = (() => {
    if (isTextEditorWrite) return `File(${item.args.filepath as string})`;
    if (isWriteTextFile) return `File(${item.args.path as string})`;
    return null;
  })();

  useEffect(() => {
    if (!wantsDiffPreview || item.resolved) return;
    setDiffStatus("loading");
    const sessionId = getSessionId();

    let url: string;
    let body: Record<string, unknown>;

    if (isTextEditorWrite) {
      url = `${window.location.origin}/api/tool-preview/text-editor`;
      // Forward the full arg set so the backend can run whichever write action
      // was requested (apply_patch, search_replace, insert_lines, …).
      body = {
        ...item.args,
        session_id: sessionId,
      };
    } else {
      url = `${window.location.origin}/api/tool-preview/write-text-file`;
      body = {
        path: item.args.path as string,
        content: item.args.content as string | undefined,
        session_memory_key: item.args.session_memory_key as string | undefined,
        session_id: sessionId,
      };
    }

    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.error) {
          setDiffStatus("error");
        } else if (data.exists === false) {
          // New file / new key — nothing to diff against
          setDiffStatus("idle");
        } else {
          setDiffData({ before: data.before as string, after: data.after as string });
          setDiffStatus("loaded");
        }
      })
      .catch(() => setDiffStatus("error"));
  }, [item.id]);  // eslint-disable-line react-hooks/exhaustive-deps

  if (item.resolved) {
    return (
      <div css={approvalResolvedBubbleCss(item.resolved.approved)}>
        {item.resolved.approved ? "✓" : "✗"} {item.tool_name}
      </div>
    );
  }
  return (
    <div css={approvalPendingCardCss}>
      <div css={approvalToolNameCss}>{item.tool_name}</div>
      <div css={approvalArgsAndDiffContainerCss}>
        {Object.keys(item.args).length > 0 && (
          <div css={approvalArgsCss}>
            <JsonArgsViewer args={item.args} toolName={item.tool_name} />
          </div>
        )}
        {wantsDiffPreview && diffStatus !== "idle" && (
          <div css={approvalArgsCss}>
            {diffStatus === "loading" && (
              <div css={diffSpinnerCss}>
                <span css={diffSpinnerDotsCss} />
                Computing diff preview...
              </div>
            )}
            {diffStatus === "error" && (
              <div css={diffErrorCss}>Could not compute diff preview.</div>
            )}
            {diffStatus === "loaded" && diffData && (
              <>
                {diffLabel && <div css={diffLabelCss}>Preview for: {diffLabel}</div>}
                <DiffViewer before={diffData.before} after={diffData.after} />
              </>
            )}
          </div>
        )}
      </div>
      <div css={approvalButtonRowCss}>
        <button
          css={approveButtonCss}
          onClick={() => onApprove(item.id)}
          disabled={wantsDiffPreview && diffStatus === "loading"}
          style={wantsDiffPreview && diffStatus === "loading" ? { opacity: 0.4, cursor: "default" } : undefined}
        >
          Approve
        </button>
        <button css={denyButtonCss} onClick={() => onDeny(item.id)}>
          Deny
        </button>
        <button
          css={denyRedirectButtonCss}
          onClick={() => setShowRedirect((r) => !r)}
        >
          Deny &amp; Redirect
        </button>
        <button
          css={denyAndStopButtonCss}
          onClick={() => onDenyAndStop(item.id)}
        >
          Deny &amp; Stop
        </button>
      </div>
      {showRedirect && (
        <div css={redirectInputAreaCss}>
          <textarea
            css={redirectTextareaCss}
            rows={3}
            placeholder="Explain why and suggest an alternative..."
            value={redirectText}
            onChange={(e) => setRedirectText(e.target.value)}
            autoFocus
          />
          <div css={redirectActionRowCss}>
            <button
              css={redirectSendButtonCss}
              disabled={!redirectText.trim()}
              onClick={() => onDenyWithRedirect(item.id, redirectText.trim())}
            >
              Send
            </button>
            <button
              css={redirectCancelButtonCss}
              onClick={() => {
                setShowRedirect(false);
                setRedirectText("");
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
