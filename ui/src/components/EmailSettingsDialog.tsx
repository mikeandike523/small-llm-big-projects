/** @jsxImportSource @emotion/react */
import { css } from "@emotion/react";
import { useMemo, useState } from "react";
import {
  HEARTBEAT_APPROVAL_POLICIES,
  HEARTBEAT_FOLLOWUP_BEHAVIORS,
  type EmailSettings,
} from "../types";
import {
  allowedSendersProblems,
  emailAddressProblem,
} from "../utils/emailAddress";

// Same choices and labels as the heartbeat dialog (automation-triggered turns).
const APPROVAL_POLICIES = HEARTBEAT_APPROVAL_POLICIES;
const FOLLOWUP_BEHAVIORS = HEARTBEAT_FOLLOWUP_BEHAVIORS;

interface Props {
  sessionId: string;
  settings: EmailSettings;
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// Styles (mirrors HeartbeatSettingsDialog.tsx's dialog conventions)
// ---------------------------------------------------------------------------

const backdropCss = css`
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.75);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
`;

const dialogCss = css`
  background: #141414;
  border: 1px solid #2a2a2a;
  border-radius: 10px;
  padding: 28px 32px;
  width: 480px;
  max-width: 95vw;
  max-height: 90vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 20px;
  font-family: "Fira Code", "Consolas", monospace;
  color: #d0d0d0;
`;

const dialogTitleCss = css`
  font-size: 15px;
  font-weight: 600;
  color: #c8c8c8;
  letter-spacing: 1px;
`;

const fieldLabelCss = css`
  font-size: 11px;
  color: #666;
  margin-bottom: 6px;
  letter-spacing: 0.5px;
  text-transform: uppercase;
`;

const controlCss = css`
  width: 100%;
  box-sizing: border-box;
  background: #0f0f0f;
  border: 1px solid #2a2a2a;
  border-radius: 5px;
  color: #d0d0d0;
  font-family: inherit;
  font-size: 12px;
  padding: 8px 10px;
  outline: none;
  &:focus {
    border-color: #3a3a5a;
  }
`;

const textareaCss = css`
  ${controlCss};
  resize: vertical;
  min-height: 90px;
`;

const hintCss = css`
  font-size: 10px;
  color: #555;
  margin-top: 4px;
`;

const fieldErrorCss = css`
  font-size: 11px;
  color: #e05555;
  margin-top: 5px;
`;

const checkboxRowCss = css`
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  font-size: 12px;
  color: #c0c0c0;
  & input {
    accent-color: #5577ee;
    cursor: pointer;
  }
`;

const footerCss = css`
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding-top: 4px;
`;

const cancelBtnCss = css`
  background: none;
  border: 1px solid #2a2a2a;
  border-radius: 5px;
  color: #666;
  font-family: inherit;
  font-size: 12px;
  padding: 8px 16px;
  cursor: pointer;
`;

const saveBtnCss = (disabled: boolean) => css`
  background: ${disabled ? "#1a1a2e" : "#1e2650"};
  border: 1px solid ${disabled ? "#2a3a6e" : "#3a5aee"};
  border-radius: 5px;
  color: ${disabled ? "#5566aa" : "#8aacff"};
  font-family: inherit;
  font-size: 12px;
  padding: 8px 20px;
  cursor: ${disabled ? "not-allowed" : "pointer"};
`;

const errorMsgCss = css`
  font-size: 11px;
  color: #cc6666;
  background: #1a0a0a;
  border: 1px solid #3a1a1a;
  border-radius: 4px;
  padding: 8px 12px;
`;

const fieldCss = css`
  display: flex;
  flex-direction: column;
`;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface ServerError {
  message: string;
  field: string | null;
}

export default function EmailSettingsDialog({
  sessionId,
  settings,
  onClose,
}: Props) {
  // Prefilled from the session's current settings each time it opens.
  const [draft, setDraft] = useState<EmailSettings>(settings);
  const [sendersText, setSendersText] = useState(
    settings.allowed_senders.join("\n"),
  );
  const [saving, setSaving] = useState(false);
  const [serverError, setServerError] = useState<ServerError | null>(null);

  const aliasProblem = useMemo(
    () => (draft.alias.trim() ? emailAddressProblem(draft.alias) : null),
    [draft.alias],
  );
  const senderProblems = useMemo(
    () => allowedSendersProblems(sendersText),
    [sendersText],
  );
  const hasLocalErrors = aliasProblem !== null || senderProblems.length > 0;
  const aliasServerError =
    serverError?.field === "alias" ? serverError.message : null;
  const sendersServerError =
    serverError?.field === "allowed_senders" ? serverError.message : null;
  const generalServerError =
    serverError && !aliasServerError && !sendersServerError
      ? serverError.message
      : null;

  async function handleSave() {
    if (saving || hasLocalErrors) return;
    setSaving(true);
    setServerError(null);
    try {
      const response = await fetch(
        `/api/sessions/${sessionId}/email-settings`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            enabled: draft.enabled,
            alias: draft.alias,
            agent_name: draft.agent_name,
            allowed_senders: sendersText,
            email_approval_policy: draft.email_approval_policy,
            followup_behavior: draft.followup_behavior,
          }),
        },
      );
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        setServerError({
          message: body?.error || "Email settings change failed",
          field: typeof body?.field === "string" ? body.field : null,
        });
        return;
      }
      onClose();
    } catch (err) {
      setServerError({
        message:
          err instanceof Error ? err.message : "Email settings change failed",
        field: null,
      });
    } finally {
      setSaving(false);
    }
  }

  const saveDisabled = saving || hasLocalErrors;

  return (
    <div css={backdropCss} onClick={onClose}>
      <div css={dialogCss} onClick={(e) => e.stopPropagation()}>
        <span css={dialogTitleCss}>EMAIL SETTINGS</span>

        {generalServerError && (
          <div css={errorMsgCss}>{generalServerError}</div>
        )}

        <label css={checkboxRowCss}>
          <input
            type="checkbox"
            checked={draft.enabled}
            onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })}
          />
          <span>Enabled</span>
        </label>

        <div css={fieldCss}>
          <label css={fieldLabelCss}>Respond to email (alias)</label>
          <input
            css={controlCss}
            value={draft.alias}
            spellCheck={false}
            placeholder="agent@example.test"
            onChange={(e) => {
              setDraft({ ...draft, alias: e.target.value });
              if (serverError?.field === "alias") setServerError(null);
            }}
          />
          {(aliasProblem || aliasServerError) && (
            <span css={fieldErrorCss}>
              {aliasServerError ?? `Alias ${aliasProblem}`}
            </span>
          )}
          <span css={hintCss}>
            Empty = this session answers nobody. Disabling keeps the alias
            reserved for this session.
          </span>
        </div>

        <div css={fieldCss}>
          <label css={fieldLabelCss}>Agent name</label>
          <input
            css={controlCss}
            value={draft.agent_name}
            maxLength={80}
            placeholder="Shown in replies and as the sender name"
            onChange={(e) => setDraft({ ...draft, agent_name: e.target.value })}
          />
        </div>

        <div css={fieldCss}>
          <label css={fieldLabelCss}>Allowed senders</label>
          <textarea
            css={textareaCss}
            value={sendersText}
            spellCheck={false}
            placeholder={"one address per line\nperson@example.test"}
            onChange={(e) => {
              setSendersText(e.target.value);
              if (serverError?.field === "allowed_senders")
                setServerError(null);
            }}
          />
          {senderProblems.map((problem) => (
            <span key={problem} css={fieldErrorCss}>
              {problem}
            </span>
          ))}
          {sendersServerError && senderProblems.length === 0 && (
            <span css={fieldErrorCss}>{sendersServerError}</span>
          )}
          <span css={hintCss}>
            One address per line, exact match (case-insensitive). Empty = answer
            nobody.
          </span>
        </div>

        <div css={fieldCss}>
          <label css={fieldLabelCss}>Message continuation mode</label>
          <select
            css={controlCss}
            value={draft.followup_behavior}
            onChange={(e) =>
              setDraft({
                ...draft,
                followup_behavior: e.target
                  .value as EmailSettings["followup_behavior"],
              })
            }
            title="Whether each email starts a new task or follows up the latest one"
          >
            {FOLLOWUP_BEHAVIORS.map(({ value, label }) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>

        <div css={fieldCss}>
          <label css={fieldLabelCss}>Automation approval mode</label>
          <select
            css={controlCss}
            value={draft.email_approval_policy}
            onChange={(e) =>
              setDraft({
                ...draft,
                email_approval_policy: e.target
                  .value as EmailSettings["email_approval_policy"],
              })
            }
            title="What happens when an email-started turn needs approval"
          >
            {APPROVAL_POLICIES.map((policy) => (
              <option key={policy} value={policy}>
                {policy}
              </option>
            ))}
          </select>
        </div>

        <div css={footerCss}>
          <button css={cancelBtnCss} onClick={onClose}>
            Cancel
          </button>
          <button
            css={saveBtnCss(saveDisabled)}
            onClick={handleSave}
            disabled={saveDisabled}
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
