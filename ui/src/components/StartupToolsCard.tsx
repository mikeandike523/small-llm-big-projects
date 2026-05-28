import { css } from "@emotion/react";
import _spin from "../css/_spin";
import { ToolCallEntry } from "../types";
import { useStickToBottom } from "use-stick-to-bottom";
import scrollbarCss from "../css/scrollBarCss";
import ToolCallCard from "./ToolCallCard";

const toolCallsGroupCss = css`
  ${scrollbarCss}
  max-height: 420px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
`;

const startupCardCss = css`
  border: 1px solid #2a3a2a;
  border-radius: 12px;
  background: #0d150d;
  box-shadow: 0 3px 16px rgba(0, 0, 0, 0.5);
  overflow: hidden;
`;

const startupCardHeaderCss = css`
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  background: #111a11;
  border-bottom: 1px solid #1e2e1e;
  font-size: 12px;
  color: #dbf0db;
  font-family: "Consolas", monospace;
  text-transform: uppercase;
  letter-spacing: 0.06em;
`;

const startupCardBodyCss = css`
  padding: 12px;
`;

const inlineSpinnerCss = css`
  display: inline-block;
  width: 10px;
  height: 10px;
  border: 2px solid rgba(100, 180, 100, 0.3);
  border-top-color: #70c870;
  border-radius: 50%;
  animation: ${_spin} 0.7s linear infinite;
  vertical-align: middle;
`;

const startupDoneBadgeCss = css`
  font-size: 11px;
  color: #50a050;
`;

export default function StartupToolCallsCard({
  toolCalls,
  done,
  onViewFull,
}: {
  toolCalls: ToolCallEntry[];
  done: boolean;
  onViewFull: (content: string) => void;
}) {
  const { scrollRef, contentRef } = useStickToBottom();

  return (
    <div css={startupCardCss}>
      <div css={startupCardHeaderCss}>
        <span>Startup Tool Calls</span>
        {done ? (
          <span css={startupDoneBadgeCss}>done ({toolCalls.length})</span>
        ) : (
          <span css={inlineSpinnerCss} />
        )}
      </div>
      <div css={startupCardBodyCss}>
        <div css={toolCallsGroupCss} ref={scrollRef}>
          <div ref={contentRef}>
            {toolCalls.map((tc) => (
              <ToolCallCard key={tc.id} tc={tc} onViewFull={onViewFull} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
