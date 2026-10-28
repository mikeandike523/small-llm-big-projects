/** @jsxImportSource @emotion/react */
import { useEffect, useRef, useState } from "react";
import FolderBrowserDialog from "./FolderBrowserDialog";
import { checkFolder, type FolderCheck } from "../api/folderBrowser";
import { FOLDER_PICKER_MODE } from "../utils/folderPickerMode";
import {
  backdropCss,
  dialogCss,
  dialogTitleCss,
  fieldLabelCss,
  cwdRowCss,
  cwdInputCss,
  cwdErrorCss,
  browseBtnCss,
  checkboxSectionCss,
  checkboxRowCss,
  checkboxInputCss,
  checkboxTextCss,
  checkboxLabelCss,
  checkboxDescCss,
  footerCss,
  cancelBtnCss,
  createBtnCss,
  errorMsgCss,
  selectCss,
  warningMsgCss,
  proceedBtnCss,
} from "../css/NewSessionDialog";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SessionDefaults {
  interim_response_as_thinking: boolean;
  load_custom_skills_tools: boolean;
  load_startup_tool_calls: boolean;
  default_profile: string | null;
  profiles: string[];
  approval_mode: string;
  approval_modes: string[];
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface Props {
  sessionDefaults: SessionDefaults;
  onCreated: (sessionId: string) => void;
  onClose: () => void;
  initialCwd?: string;
}

// A problem with the chosen working directory, from POST /api/sessions or
// /api/folder-check. Cleared whenever the path is edited or re-picked.
// - error:   red text under the field; Create stays disabled.
// - warning: privileged / not-recommended folder; the footer offers
//            Cancel + "Proceed with caution" for exactly `path`.
type CwdIssue =
  | { kind: "error"; message: string }
  | { kind: "warning"; message: string; reason: string | null; path: string };

function issueFromCheck(check: FolderCheck, path: string): CwdIssue | null {
  if (check.status === "error")
    return { kind: "error", message: check.message ?? "Invalid folder." };
  if (check.status === "warning")
    return {
      kind: "warning",
      message: check.message ?? "",
      reason: check.reason,
      path,
    };
  return null;
}

// ---------------------------------------------------------------------------
// Checkbox option config
// ---------------------------------------------------------------------------

interface CheckOption {
  key: keyof SessionDefaults;
  label: string;
  flag: string;
  desc: string;
}

const OPTIONS: CheckOption[] = [
  {
    key: "load_custom_skills_tools",
    label: "Load custom skills and tools",
    flag: "--load-custom-skills-tools",
    desc: "Load custom skills and tools from the skills/ and tools/ directories in the working directory.",
  },
  {
    key: "load_startup_tool_calls",
    label: "Run startup tool calls",
    flag: "--load-startup-tool-calls",
    desc: "Execute tool calls from startup_tool_calls.json on session start.",
  },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function NewSessionDialog({
  sessionDefaults,
  onCreated,
  onClose,
  initialCwd,
}: Props) {
  const [cwd, setCwd] = useState(initialCwd ?? "");
  // Issued by the backend when the dialog opens, so the suggested workspace
  // folder can be named after the session it will belong to.
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [workspaceDir, setWorkspaceDir] = useState<string>("");
  const [flags, setFlags] = useState<SessionDefaults>(() => ({
    ...sessionDefaults,
    // Default all option checkboxes to checked when the dialog opens.
    load_custom_skills_tools: true,
    load_startup_tool_calls: true,
  }));
  const [selectedProfile, setSelectedProfile] = useState<string>(
    sessionDefaults.default_profile ?? "",
  );
  const [selectedApprovalMode, setSelectedApprovalMode] = useState<string>(
    sessionDefaults.approval_mode ?? "default",
  );
  const [browsing, setBrowsing] = useState(false);
  const [browserOpen, setBrowserOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cwdIssue, setCwdIssue] = useState<CwdIssue | null>(null);
  // Bumped on every cwd change so a late picker check can't apply to a newer path.
  const cwdVersionRef = useRef(0);

  const cwdEmpty = cwd.trim() === "";

  // Fetch a session id and its workspace folder on mount; the folder becomes
  // the default CWD unless initialCwd was provided. If this fails, the backend
  // generates an id at creation instead.
  useEffect(() => {
    fetch("/api/sessions/new-id")
      .then((r) => r.json())
      .then((d) => {
        if (!d.session_id || !d.workspace_dir) return;
        setSessionId(d.session_id);
        setWorkspaceDir(d.workspace_dir);
        if (!initialCwd) setCwd(d.workspace_dir);
      })
      .catch(() => {});
  }, []);

  // Close on Escape (the folder browser handles its own Escape while open).
  useEffect(() => {
    if (browserOpen) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, browserOpen]);

  function changeCwd(value: string) {
    cwdVersionRef.current += 1;
    setCwd(value);
    setCwdIssue(null);
  }

  // A picked folder is checked right away, so a privileged or unusable pick
  // shows its warning/error before Create is even clicked.
  async function applyPickedFolder(path: string) {
    changeCwd(path);
    const version = cwdVersionRef.current;
    try {
      const check = await checkFolder(path, sessionId);
      if (cwdVersionRef.current === version)
        setCwdIssue(issueFromCheck(check, path));
    } catch {
      // Create re-validates on the server anyway.
    }
  }

  async function handleBrowse() {
    const desktop = window.slbpDesktop;
    if (FOLDER_PICKER_MODE === "remote" || !desktop) {
      setError(null);
      setBrowserOpen(true);
      return;
    }
    setBrowsing(true);
    try {
      const picked = await desktop.pickFolder(cwd);
      if (picked) await applyPickedFolder(picked);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not open folder picker");
    } finally {
      setBrowsing(false);
    }
  }

  async function handleCreate(allowPrivilegedCwd = false) {
    if (creating) return;
    setCreating(true);
    setError(null);

    const payload: Record<string, unknown> = {
      initial_cwd: cwd,
      session_id: sessionId ?? undefined,
      interim_response_as_thinking:
        sessionDefaults.interim_response_as_thinking,
      profile_name: selectedProfile || null,
      approval_mode: selectedApprovalMode,
      load_custom_skills_tools: flags.load_custom_skills_tools,
      // The server resolves the cwd and looks for startup_tool_calls.json in it.
      load_startup_tool_calls: flags.load_startup_tool_calls,
      allow_privileged_cwd: allowPrivilegedCwd,
    };

    try {
      const res = await fetch("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        if (body.code === "invalid_cwd" || body.code === "privileged_cwd") {
          setCwdIssue(
            body.code === "invalid_cwd"
              ? { kind: "error", message: body.error }
              : {
                  kind: "warning",
                  message: body.error,
                  reason: body.reason ?? null,
                  path: cwd,
                },
          );
          setCreating(false);
          return;
        }
        throw new Error(body.error ?? `Server returned ${res.status}`);
      }
      const data = await res.json();
      if (!data.session_id)
        throw new Error("Server did not return a session_id.");
      onCreated(data.session_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      setCreating(false);
    }
  }

  function toggleFlag(key: keyof SessionDefaults) {
    setFlags((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  return (
    <div
      css={backdropCss}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div css={dialogCss}>
        <div css={dialogTitleCss}>New Session</div>

        <div>
          <div css={fieldLabelCss}>Working Directory</div>
          <div css={cwdRowCss}>
            <input
              css={cwdInputCss(cwdEmpty || cwdIssue?.kind === "error")}
              type="text"
              value={cwd}
              onChange={(e) => changeCwd(e.target.value)}
              placeholder={workspaceDir || "/path/to/project"}
              spellCheck={false}
            />
            <button
              css={browseBtnCss(browsing)}
              onClick={handleBrowse}
              disabled={browsing}
              title={
                FOLDER_PICKER_MODE === "native"
                  ? "Open folder picker"
                  : "Browse folders on the server"
              }
            >
              {browsing ? "..." : "Browse"}
            </button>
          </div>
          {cwdEmpty && (
            <div css={cwdErrorCss}>
              Working directory is required.{" "}
              {workspaceDir ? (
                <span>
                  No specific project?{" "}
                  <span
                    style={{ cursor: "pointer", textDecoration: "underline" }}
                    onClick={() => changeCwd(workspaceDir)}
                  >
                    Use new session workspace
                  </span>
                </span>
              ) : (
                "Enter a directory path to continue."
              )}
            </div>
          )}
          {cwdIssue?.kind === "error" && (
            <div css={cwdErrorCss}>{cwdIssue.message}</div>
          )}
        </div>

        <div>
          <div css={fieldLabelCss}>Options</div>
          <div css={checkboxSectionCss}>
            {OPTIONS.map((opt) => (
              <label key={opt.key} css={checkboxRowCss}>
                <input
                  type="checkbox"
                  css={checkboxInputCss}
                  checked={Boolean(flags[opt.key])}
                  onChange={() => toggleFlag(opt.key)}
                />
                <div css={checkboxTextCss}>
                  <span css={checkboxLabelCss}>
                    {opt.label}
                    <span style={{ color: "#3a3a5a", marginLeft: 6 }}>
                      {opt.flag}
                    </span>
                  </span>
                  <span css={checkboxDescCss}>{opt.desc}</span>
                </div>
              </label>
            ))}
          </div>
        </div>

        {sessionDefaults.profiles.length > 0 && (
          <div>
            <div css={fieldLabelCss}>Starting Profile</div>
            <select
              css={selectCss}
              value={selectedProfile}
              onChange={(e) => setSelectedProfile(e.target.value)}
            >
              {sessionDefaults.profiles.map((p) => (
                <option key={p} value={p}>
                  {p}
                  {p === sessionDefaults.default_profile ? " (default)" : ""}
                </option>
              ))}
            </select>
          </div>
        )}

        <div>
          <div css={fieldLabelCss}>Approval Mode</div>
          <select
            css={selectCss}
            value={selectedApprovalMode}
            onChange={(e) => setSelectedApprovalMode(e.target.value)}
          >
            {(
              sessionDefaults.approval_modes ?? [
                "default",
                "auto-accept-edits",
                "full-auto",
              ]
            ).map((mode) => (
              <option key={mode} value={mode}>
                {mode}
              </option>
            ))}
          </select>
        </div>

        {error && <div css={errorMsgCss}>{error}</div>}

        {cwdIssue?.kind === "warning" ? (
          <>
            <div css={warningMsgCss}>
              {cwdIssue.message}
              {cwdIssue.reason && <div>Matched: {cwdIssue.reason}</div>}
            </div>
            <div css={footerCss}>
              {/* Dismisses only the warning; the dialog stays open. */}
              <button
                css={cancelBtnCss}
                onClick={() => setCwdIssue(null)}
                disabled={creating}
              >
                Cancel
              </button>
              <button
                css={proceedBtnCss(creating)}
                onClick={() => handleCreate(true)}
                disabled={creating}
              >
                {creating ? "Creating..." : "Proceed with caution"}
              </button>
            </div>
          </>
        ) : (
          <div css={footerCss}>
            <button css={cancelBtnCss} onClick={onClose} disabled={creating}>
              Cancel
            </button>
            <button
              css={createBtnCss(creating || cwdIssue !== null)}
              onClick={() => handleCreate()}
              disabled={creating || cwdEmpty || cwdIssue !== null}
            >
              {creating ? "Creating..." : "Create Session"}
            </button>
          </div>
        )}
      </div>

      {browserOpen && (
        <FolderBrowserDialog
          onSelect={(path) => {
            setBrowserOpen(false);
            void applyPickedFolder(path);
          }}
          onCancel={() => setBrowserOpen(false)}
          onFatal={(message) => {
            setBrowserOpen(false);
            setError(message);
          }}
        />
      )}
    </div>
  );
}
