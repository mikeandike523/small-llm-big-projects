import { css } from "@emotion/react";
import { useState } from "react";
import { FaRocket } from "react-icons/fa";
import _spin from "../../css/_spin";
import type { ToolCallEntry } from "../../types";
import StartupToolCallsCard from "../../components/StartupToolsCard";

const headerButtonCss = css`
  background: #101722;
  border: 1px solid #2a3a2a;
  border-radius: 4px;
  color: #8ac88a;
  display: flex;
  align-items: center;
  gap: 6px;
  font-family: inherit;
  font-size: 11px;
  padding: 4px 8px;
  cursor: pointer;
  &:hover {
    background: #121c12;
  }
`;

const spinnerCss = css`
  display: inline-block;
  width: 9px;
  height: 9px;
  border: 2px solid rgba(100, 180, 100, 0.3);
  border-top-color: #70c870;
  border-radius: 50%;
  animation: ${_spin} 0.7s linear infinite;
`;

// Below ToolModal (z-index 1000), which opens on top of this for full results.
const overlayCss = css`
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 900;
`;

const dialogCss = css`
  width: 80%;
  max-width: 900px;
  display: flex;
  flex-direction: column;
  gap: 8px;
`;

const closeRowCss = css`
  display: flex;
  justify-content: flex-end;
`;

const closeButtonCss = css`
  background: #101722;
  border: 1px solid #2a3a6e;
  border-radius: 4px;
  color: #8aacff;
  font-size: 12px;
  font-family: inherit;
  padding: 4px 12px;
  cursor: pointer;
  &:hover {
    background: #16213a;
  }
`;

/**
 * Header button for the session's startup tool calls (shown only when there
 * are any). Opens them in a modal, keeping them out of the way of the turn.
 */
export default function StartupToolsButton({
  toolCalls,
  done,
  onViewFull,
}: {
  toolCalls: ToolCallEntry[];
  done: boolean;
  onViewFull: (content: string) => void;
}) {
  const [open, setOpen] = useState(false);
  if (toolCalls.length === 0) return null;
  return (
    <>
      <button
        css={headerButtonCss}
        onClick={() => setOpen(true)}
        title="View the session's startup tool calls"
        aria-label="Startup tool calls"
      >
        {done ? <FaRocket size={11} /> : <span css={spinnerCss} />}
        Startup ({toolCalls.length})
      </button>
      {open && (
        <StartupToolsModal
          toolCalls={toolCalls}
          done={done}
          onViewFull={onViewFull}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}

function StartupToolsModal({
  toolCalls,
  done,
  onViewFull,
  onClose,
}: {
  toolCalls: ToolCallEntry[];
  done: boolean;
  onViewFull: (content: string) => void;
  onClose: () => void;
}) {
  return (
    <div css={overlayCss} onClick={onClose}>
      <div css={dialogCss} onClick={(e) => e.stopPropagation()}>
        <StartupToolCallsCard
          toolCalls={toolCalls}
          done={done}
          onViewFull={onViewFull}
        />
        <div css={closeRowCss}>
          <button css={closeButtonCss} onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
