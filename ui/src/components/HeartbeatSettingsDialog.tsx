/** @jsxImportSource @emotion/react */
import { css } from "@emotion/react";
import { useEffect, useState } from "react";
import {
  HEARTBEAT_APPROVAL_POLICIES,
  type HeartbeatSettings,
} from "../types";
import { formatIntervalMinutes } from "../utils/formatInterval";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface Props {
  sessionId: string;
  settings: HeartbeatSettings;
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// Styles (mirrors NewSessionDialog.tsx's dialog conventions)
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
  &::-webkit-scrollbar {
    width: 5px;
  }
  &::-webkit-scrollbar-track {
    background: #0a0a0a;
  }
  &::-webkit-scrollbar-thumb {
    background: #3a3a3a;
    border-radius: 3px;
  }
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

const selectCss = css`
  width: 100%;
  background: #0f0f0f;
  border: 1px solid #2a2a2a;
  border-radius: 5px;
  color: #d0d0d0;
  font-family: inherit;
  font-size: 12px;
  padding: 8px 10px;
  cursor: pointer;
  outline: none;
  &:focus {
    border-color: #3a3a5a;
  }
`;

const textareaCss = css`
  width: 100%;
  background: #0f0f0f;
  border: 1px solid #2a2a2a;
  border-radius: 5px;
  color: #d0d0d0;
  font-family: inherit;
  font-size: 12px;
  padding: 8px 10px;
  outline: none;
  resize: vertical;
  min-height: 70px;
  &:focus {
    border-color: #3a3a5a;
  }
`;

const checkboxRowCss = css`
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
`;

const checkboxInputCss = css`
  accent-color: #5577ee;
  cursor: pointer;
  flex-shrink: 0;
`;

const checkboxLabelCss = css`
  font-size: 12px;
  color: #c0c0c0;
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
  &:hover {
    border-color: #444;
    color: #888;
  }
`;

const saveBtnCss = (loading: boolean) => css`
  background: ${loading ? "#1a1a2e" : "#1e2650"};
  border: 1px solid ${loading ? "#2a3a6e" : "#3a5aee"};
  border-radius: 5px;
  color: ${loading ? "#5566aa" : "#8aacff"};
  font-family: inherit;
  font-size: 12px;
  padding: 8px 20px;
  cursor: ${loading ? "not-allowed" : "pointer"};
  transition: background 0.12s;
  &:hover {
    background: ${loading ? "#1a1a2e" : "#222a5e"};
  }
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

export default function HeartbeatSettingsDialog({
  sessionId,
  settings,
  onClose,
}: Props) {
  const [draft, setDraft] = useState<HeartbeatSettings>(settings);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [intervals, setIntervals] = useState<number[] | null>(null);
  const [intervalsLoading, setIntervalsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function fetchIntervals() {
      try {
        const res = await fetch("/api/heartbeat-intervals");
        if (!res.ok) throw new Error("Failed to fetch intervals");
        const data = await res.json();
        if (!cancelled) {
          setIntervals(data.intervals ?? []);
          setIntervalsLoading(false);
        }
      } catch {
        if (!cancelled) setIntervalsLoading(false);
      }
    }
    fetchIntervals();
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSave() {
    if (saving) return;
    setSaving(true);
    setError(null);
    try {
      const response = await fetch(
        `/api/sessions/${sessionId}/heartbeat-settings`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(draft),
        },
      );
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.error || "Heartbeat settings change failed");
      }
      onClose();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Heartbeat settings change failed",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div css={backdropCss} onClick={onClose}>
      <div css={dialogCss} onClick={(e) => e.stopPropagation()}>
        <span css={dialogTitleCss}>HEARTBEAT SETTINGS</span>

        {error && <div css={errorMsgCss}>{error}</div>}

        <label css={checkboxRowCss}>
          <input
            css={checkboxInputCss}
            type="checkbox"
            checked={draft.enabled}
            onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })}
          />
          <span css={checkboxLabelCss}>Enabled</span>
        </label>

        <div css={fieldCss}>
          <label css={fieldLabelCss}>Interval</label>
          <select
            css={selectCss}
            value={draft.interval_minutes}
            disabled={intervalsLoading}
            onChange={(e) =>
              setDraft({ ...draft, interval_minutes: Number(e.target.value) })
            }
          >
            {intervalsLoading ? (
              <option value={draft.interval_minutes}>Loading…</option>
            ) : (
              (intervals ?? []).map((minutes) => (
                <option key={minutes} value={minutes}>
                  {formatIntervalMinutes(minutes)}
                </option>
              ))
            )}
          </select>
        </div>

        <div css={fieldCss}>
          <label css={fieldLabelCss}>Heartbeat instructions</label>
          <textarea
            css={textareaCss}
            value={draft.instructions}
            onChange={(e) =>
              setDraft({ ...draft, instructions: e.target.value })
            }
            placeholder="What should the agent do on each heartbeat?"
          />
        </div>

        <div css={fieldCss}>
          <label css={fieldLabelCss}>Heartbeat approval policy</label>
          <select
            css={selectCss}
            value={draft.heartbeat_approval_policy}
            onChange={(e) =>
              setDraft({
                ...draft,
                heartbeat_approval_policy: e.target
                  .value as HeartbeatSettings["heartbeat_approval_policy"],
              })
            }
          >
            {HEARTBEAT_APPROVAL_POLICIES.map((policy) => (
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
            css={saveBtnCss(saving || intervalsLoading)}
            onClick={handleSave}
            disabled={saving || intervalsLoading}
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
