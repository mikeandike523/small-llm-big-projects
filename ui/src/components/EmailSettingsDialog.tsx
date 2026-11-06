/** @jsxImportSource @emotion/react */
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
import {
  backdropCss,
  checkboxRowCss,
  controlCss,
  dialogCss,
  dialogTitleCss,
  errorMsgCss,
  fieldCss,
  fieldErrorCss,
  fieldLabelCss,
  footerCss,
  hintCss,
  saveBtnCss,
  secondaryBtnCss,
  textareaCss,
} from "../css/AgentSettingsDialog";

// Same choices and labels as the heartbeat dialog (automation-triggered turns).
const APPROVAL_POLICIES = HEARTBEAT_APPROVAL_POLICIES;
const FOLLOWUP_BEHAVIORS = HEARTBEAT_FOLLOWUP_BEHAVIORS;

interface Props {
  sessionId: string;
  settings: EmailSettings;
  onClose: () => void;
}

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
          <button css={secondaryBtnCss} onClick={onClose}>
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
