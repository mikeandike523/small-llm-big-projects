/** @jsxImportSource @emotion/react */
import { useMemo, useState } from "react";
import {
  AUTOMATION_APPROVAL_POLICIES,
  type AgentSummary,
  type AutomationApprovalPolicy,
} from "../types";
import {
  allowedSendersProblems,
  emailAddressProblem,
} from "../utils/emailAddress";
import {
  backdropCss,
  dialogCss,
  dialogTitleCss,
  fieldLabelCss,
  controlCss,
  textareaCss,
  hintCss,
  fieldErrorCss,
  checkboxRowCss,
  footerCss,
  secondaryBtnCss,
  dangerBtnCss,
  saveBtnCss,
  errorMsgCss,
  fieldCss,
} from "../css/AgentSettingsDialog";
import ConfirmDialog from "./ConfirmDialog";
import type { SessionDefaults } from "./NewSessionDialog";

interface Props {
  /** The agent to edit, or null for the New Agent wizard. */
  agent: AgentSummary | null;
  sessionDefaults: SessionDefaults;
  onChanged: () => void;
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface ServerError {
  message: string;
  field: string | null;
}

async function requestJson(
  url: string,
  method: string,
  body?: unknown,
): Promise<ServerError | null> {
  try {
    const response = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (response.ok) return null;
    const data = await response.json().catch(() => null);
    return {
      message: data?.error || `Request failed (${response.status})`,
      field: typeof data?.field === "string" ? data.field : null,
    };
  } catch (err) {
    return {
      message: err instanceof Error ? err.message : "Could not reach server",
      field: null,
    };
  }
}

export default function AgentSettingsDialog({
  agent,
  sessionDefaults,
  onChanged,
  onClose,
}: Props) {
  // Whether the name + email pair is committed. The wizard commits it on create.
  const [registered, setRegistered] = useState(agent?.email != null);
  const [name, setName] = useState(agent?.name ?? "");
  const [email, setEmail] = useState(agent?.email ?? "");
  const [enabled, setEnabled] = useState(agent?.enabled ?? true);
  const [sendersText, setSendersText] = useState(
    (agent?.allowed_senders ?? []).join("\n"),
  );
  const [profile, setProfile] = useState(
    agent?.profile_name ?? sessionDefaults.default_profile ?? "",
  );
  const [approvalMode, setApprovalMode] = useState(
    agent?.approval_mode ?? sessionDefaults.approval_mode,
  );
  const [policy, setPolicy] = useState<AutomationApprovalPolicy>(
    agent?.automation_approval_policy ?? "wait-for-human",
  );
  const [saving, setSaving] = useState(false);
  const [serverError, setServerError] = useState<ServerError | null>(null);
  const [confirming, setConfirming] = useState<"unregister" | "delete" | null>(
    null,
  );

  const identityEditable = !registered;
  const nameProblem = identityEditable && !name.trim() ? "is required" : null;
  const emailProblem = useMemo(() => {
    if (!identityEditable) return null;
    return email.trim() ? emailAddressProblem(email) : "is required";
  }, [email, identityEditable]);
  const senderProblems = useMemo(
    () => allowedSendersProblems(sendersText),
    [sendersText],
  );
  const fieldServerError = (field: string) =>
    serverError?.field === field ? serverError.message : null;
  const generalServerError =
    serverError &&
    !["name", "email", "allowed_senders"].includes(serverError.field ?? "")
      ? serverError.message
      : null;
  const identityInvalid = nameProblem !== null || emailProblem !== null;

  const settingsBody = {
    enabled,
    allowed_senders: sendersText,
    profile_name: profile,
    approval_mode: approvalMode,
    automation_approval_policy: policy,
  };

  async function run(action: () => Promise<ServerError | null>) {
    setSaving(true);
    setServerError(null);
    const error = await action();
    setSaving(false);
    setServerError(error);
    if (error === null) onChanged();
    return error === null;
  }

  async function handleSave() {
    if (agent === null) {
      const done = await run(() =>
        requestJson("/api/agents", "POST", { name, email, ...settingsBody }),
      );
      if (done) onClose();
      return;
    }
    const done = await run(() =>
      requestJson(`/api/agents/${agent.id}`, "PATCH", settingsBody),
    );
    if (done) onClose();
  }

  async function handleRegister() {
    if (agent === null) return;
    const done = await run(() =>
      requestJson(`/api/agents/${agent.id}/register`, "POST", { name, email }),
    );
    if (done) setRegistered(true);
  }

  async function handleUnregister() {
    if (agent === null) return;
    const done = await run(() =>
      requestJson(`/api/agents/${agent.id}/unregister`, "POST"),
    );
    setConfirming(null);
    if (done) {
      setRegistered(false);
      setName("");
      setEmail("");
    }
  }

  async function handleDelete() {
    if (agent === null) return;
    const done = await run(() =>
      requestJson(`/api/agents/${agent.id}`, "DELETE"),
    );
    setConfirming(null);
    if (done) onClose();
  }

  const saveDisabled =
    saving ||
    senderProblems.length > 0 ||
    !profile ||
    (agent === null && identityInvalid);

  return (
    <div css={backdropCss} onClick={onClose}>
      <div css={dialogCss} onClick={(e) => e.stopPropagation()}>
        <span css={dialogTitleCss}>
          {agent === null ? "NEW AGENT" : "AGENT SETTINGS"}
        </span>

        {generalServerError && (
          <div css={errorMsgCss}>{generalServerError}</div>
        )}

        <div css={fieldCss}>
          <label css={fieldLabelCss}>Agent name</label>
          <input
            css={controlCss}
            value={name}
            maxLength={80}
            readOnly={!identityEditable}
            placeholder="Shown in replies and as the sender name"
            onChange={(e) => {
              setName(e.target.value);
              if (serverError?.field === "name") setServerError(null);
            }}
          />
          {fieldServerError("name") && (
            <span css={fieldErrorCss}>{fieldServerError("name")}</span>
          )}
        </div>

        <div css={fieldCss}>
          <label css={fieldLabelCss}>Email</label>
          <input
            css={controlCss}
            value={email}
            spellCheck={false}
            readOnly={!identityEditable}
            placeholder="agent@example.test"
            onChange={(e) => {
              setEmail(e.target.value);
              if (serverError?.field === "email") setServerError(null);
            }}
          />
          {(fieldServerError("email") ||
            (email.trim() && emailProblem !== null)) && (
            <span css={fieldErrorCss}>
              {fieldServerError("email") ?? `Email ${emailProblem}`}
            </span>
          )}
          <span css={hintCss}>
            {registered
              ? "This name and email belong to this agent, even while it is disabled. Unregister to release them."
              : agent === null
                ? "Creating the agent commits this name and email. Both must be unique, ignoring case, and the name also sets the agent's folder."
                : "Register to claim a name and email. Only mail received after that is answered."}
          </span>
          {agent !== null && (
            <div style={{ display: "flex", marginTop: 8 }}>
              {registered ? (
                <button
                  css={secondaryBtnCss}
                  disabled={saving}
                  onClick={() => setConfirming("unregister")}
                >
                  Unregister name and email
                </button>
              ) : (
                <button
                  css={saveBtnCss(saving || identityInvalid)}
                  disabled={saving || identityInvalid}
                  onClick={handleRegister}
                >
                  Register name and email
                </button>
              )}
            </div>
          )}
        </div>

        <label css={checkboxRowCss}>
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
          />
          <span>Enabled (answers email)</span>
        </label>

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
          {fieldServerError("allowed_senders") &&
            senderProblems.length === 0 && (
              <span css={fieldErrorCss}>
                {fieldServerError("allowed_senders")}
              </span>
            )}
          <span css={hintCss}>
            One address per line, exact match (case-insensitive). Empty = answer
            nobody.
          </span>
        </div>

        <div css={fieldCss}>
          <label css={fieldLabelCss}>Profile</label>
          <select
            css={controlCss}
            value={profile}
            onChange={(e) => setProfile(e.target.value)}
            title="Takes effect on each session's next LLM request"
          >
            {sessionDefaults.profiles.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </div>

        <div css={fieldCss}>
          <label css={fieldLabelCss}>Session approval mode</label>
          <select
            css={controlCss}
            value={approvalMode}
            onChange={(e) => setApprovalMode(e.target.value)}
            title="Takes effect on each session's next tool approval check"
          >
            {sessionDefaults.approval_modes.map((mode) => (
              <option key={mode} value={mode}>
                {mode}
              </option>
            ))}
          </select>
        </div>

        <div css={fieldCss}>
          <label css={fieldLabelCss}>Automation approval mode</label>
          <select
            css={controlCss}
            value={policy}
            onChange={(e) =>
              setPolicy(e.target.value as AutomationApprovalPolicy)
            }
            title="What happens when an email-started turn needs approval"
          >
            {AUTOMATION_APPROVAL_POLICIES.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </div>

        {agent !== null && <span css={hintCss}>Folder: {agent.workspace}</span>}

        <div css={footerCss}>
          {agent !== null && !registered && (
            <button
              css={dangerBtnCss}
              disabled={saving}
              onClick={() => setConfirming("delete")}
            >
              Delete agent
            </button>
          )}
          <button css={secondaryBtnCss} onClick={onClose}>
            Cancel
          </button>
          <button
            css={saveBtnCss(saveDisabled)}
            onClick={handleSave}
            disabled={saveDisabled}
          >
            {saving ? "Saving…" : agent === null ? "Create agent" : "Save"}
          </button>
        </div>
      </div>

      {confirming === "unregister" && (
        <div onClick={(e) => e.stopPropagation()}>
          <ConfirmDialog
            title="Unregister Name and Email?"
            confirmLabel="Unregister"
            busyLabel="Unregistering..."
            busy={saving}
            onConfirm={handleUnregister}
            onCancel={() => setConfirming(null)}
          >
            This agent will stop answering email, and its queued mail is
            discarded. Another agent can then claim this name and email. Its
            sessions and folder are kept.
          </ConfirmDialog>
        </div>
      )}
      {confirming === "delete" && (
        <div onClick={(e) => e.stopPropagation()}>
          <ConfirmDialog
            title="Delete Agent?"
            confirmLabel="Delete"
            busyLabel="Deleting..."
            busy={saving}
            onConfirm={handleDelete}
            onCancel={() => setConfirming(null)}
          >
            This permanently deletes the agent and all of its sessions. Its
            folder stays on disk, and an agent created with the same name will
            reuse it.
          </ConfirmDialog>
        </div>
      )}
    </div>
  );
}
