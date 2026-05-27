import { css } from "@emotion/react";
import { MdOpenInFull } from "react-icons/md";
import _spin from "../css/_spin";
import { ToolCallEntry } from "../types";
import { useStickToBottom } from "use-stick-to-bottom";
import { MAX_TOOL_CHARS } from "../constants/tool-ui-constants";
import {
  toolArgsCss,
  toolCallCss,
  toolHeaderCss,
  toolResultCss,
  toolResultContainerCss,
  expandButtonCss,
} from "../css/tool-ui-css";
import scrollbarCss from "../css/scrollBarCss";
import JsonArgsViewer from "./JsonArgsViewer";
import Ansi from "ansi-to-react";

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
            {toolCalls.map((tc) => {
              const hasResult = tc.result !== undefined;
              const truncated = hasResult && tc.result!.length > MAX_TOOL_CHARS;
              const displayResult = hasResult
                ? truncated
                  ? tc.result!.slice(0, MAX_TOOL_CHARS) +
                    `... (${tc.result!.length - MAX_TOOL_CHARS} more)`
                  : tc.result!
                : undefined;

              return (
                <div key={tc.id} css={toolCallCss}>
                  <div css={toolHeaderCss}>
                    <span>⚙ {tc.name}</span>
                  </div>
                  {Object.keys(tc.args).length > 0 && (
                    <div css={toolArgsCss}>
                      <JsonArgsViewer args={tc.args} />
                    </div>
                  )}
                  {hasResult && (
                    <div css={toolResultContainerCss}>
                      <div css={toolResultCss}>
                        <Ansi>{displayResult}</Ansi>
                      </div>
                      {truncated && (
                        <button
                          css={expandButtonCss}
                          onClick={() => onViewFull(tc.result!)}
                          title="View full result"
                        >
                          <MdOpenInFull />
                        </button>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
