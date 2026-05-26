import { useState } from "react";
import { css, keyframes } from "@emotion/react";

import { ToolCallEntry } from "../types";
import ElapsedTimer from "./ElapsedTimer";
import JsonArgsViewer from "./JsonArgsViewer";
import Ansi from "ansi-to-react";
import { MAX_TOOL_CHARS } from "../constants/tool-ui-constants";
import {
  toolArgsCss,
  toolCallCss,
  toolHeaderCss,
  toolResultCss,
  viewFullButtonCss,
} from "../css/tool-ui-css";

const MAX_STREAMING_CHARS = 300;

const _streamPulse = keyframes`
  0%, 100% { opacity: 0.35; }
  50%       { opacity: 1; }
`;

const streamingDotCss = css`
  display: inline-block;
  width: 6px;
  height: 6px;
  background: #70a0ff;
  border-radius: 50%;
  margin-left: 6px;
  vertical-align: middle;
  animation: ${_streamPulse} 1s ease-in-out infinite;
`;

const deniedToolResultCss = css`
  background: #1a0505;
  color: #f87171;
  padding: 8px 14px;
  font-family: "Consolas", monospace;
  white-space: pre-wrap;
  word-break: break-word;
  border-top: 1px solid #5a1a1a;
`;

const streamingResultCss = css`
  background: #050e05;
  color: #5a8a5a;
  padding: 8px 14px;
  font-family: "Consolas", monospace;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
  border-top: 1px solid #0f200f;
`;

// ---- Patch rewrite styles ----

const _rewritePulse = keyframes`
  0%, 100% { opacity: 0.5; }
  50%       { opacity: 1; }
`;

const rewriteProgressCss = css`
  display: block;
  padding: 5px 14px;
  font-family: "Consolas", monospace;
  font-size: 11px;
  color: #c49a4a;
  background: #1a1500;
  border-top: 1px solid #3a2e00;
  animation: ${_rewritePulse} 1.2s ease-in-out infinite;
`;

const rewriteFailedCss = css`
  display: block;
  padding: 5px 14px;
  font-family: "Consolas", monospace;
  font-size: 11px;
  color: #e06060;
  background: #150808;
  border-top: 1px solid #3a1010;
`;

const rewriteSuccessBadgeCss = css`
  display: block;
  padding: 5px 14px;
  font-family: "Consolas", monospace;
  font-size: 11px;
  color: #6ec87e;
  background: #081508;
  border-top: 1px solid #103010;
`;

const rewrittenArgsBannerCss = css`
  padding: 4px 14px;
  font-family: "Consolas", monospace;
  font-size: 10px;
  color: #6ec87e;
  background: #0d1f0d;
  border-top: 1px solid #1a3a1a;
  text-transform: uppercase;
  letter-spacing: 0.06em;
`;

const originalArgsToggleCss = css`
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 14px;
  font-family: "Consolas", monospace;
  font-size: 11px;
  color: #8888aa;
  background: #12122a;
  border-top: 1px solid #22224a;
  cursor: pointer;
  user-select: none;
  &:hover {
    color: #aaaacc;
    background: #18183a;
  }
`;

export default function ToolCallCard({
  tc,
  onViewFull,
}: {
  tc: ToolCallEntry;
  onViewFull: (c: string) => void;
}) {
  const hasResult = tc.result !== undefined;
  const isStreaming = !hasResult && tc.streamingResult !== undefined;
  const truncated = hasResult && tc.result!.length > MAX_TOOL_CHARS;
  const isDenied = hasResult && tc.result!.startsWith("Error: NOT Approved.");

  const rewrite = tc.patchRewrite;
  const rewriteSucceeded = rewrite?.status === "success";
  const rewriteInProgress = rewrite?.status === "in_progress";
  const rewriteFailed = rewrite?.status === "failed";

  // Original args section is collapsed by default when a successful rewrite exists.
  const [originalExpanded, setOriginalExpanded] = useState(false);

  let displayResult: string | undefined;
  if (hasResult) {
    displayResult = truncated
      ? tc.result!.slice(0, MAX_TOOL_CHARS) +
        `... (${tc.result!.length - MAX_TOOL_CHARS} more)`
      : tc.result!;
  } else if (isStreaming) {
    const sr = tc.streamingResult!;
    displayResult =
      sr.length > MAX_STREAMING_CHARS
        ? `[...+${sr.length - MAX_STREAMING_CHARS} chars]\n` +
          sr.slice(-MAX_STREAMING_CHARS)
        : sr;
  }

  // When rewrite succeeded, the first viewer shows original (possibly-broken) args
  // and the second viewer shows tc.args (which was updated to the rewritten patch).
  const firstViewerArgs = rewriteSucceeded
    ? (rewrite!.originalArgs as Record<string, unknown>)
    : tc.args;

  return (
    <div css={toolCallCss}>
      <div css={toolHeaderCss}>
        <span>
          ⚙ {tc.name}
          {isStreaming && <span css={streamingDotCss} />}
        </span>
        <span
          css={css`
            display: flex;
            align-items: center;
            gap: 6px;
          `}
        >
          <ElapsedTimer startedAt={tc.startedAt} finishedAt={tc.finishedAt} />
          {truncated && (
            <button
              css={viewFullButtonCss}
              onClick={() => onViewFull(tc.result!)}
            >
              view full
            </button>
          )}
        </span>
      </div>

      {/* First args section: original args, collapsible when rewrite succeeded */}
      {Object.keys(firstViewerArgs).length > 0 && (
        <>
          {rewriteSucceeded ? (
            <>
              <div
                css={originalArgsToggleCss}
                onClick={() => setOriginalExpanded((e) => !e)}
              >
                <span>{originalExpanded ? "▼" : "▶"}</span>
                <span>Original args (pre-rewrite)</span>
              </div>
              {originalExpanded && (
                <div css={toolArgsCss}>
                  <JsonArgsViewer args={firstViewerArgs} />
                </div>
              )}
            </>
          ) : (
            <div css={toolArgsCss}>
              <JsonArgsViewer args={firstViewerArgs} />
            </div>
          )}
        </>
      )}

      {/* Rewrite status span */}
      {rewriteInProgress && (
        <span css={rewriteProgressCss}>
          {rewrite!.attempt > 0
            ? `Rewriting patch... (attempt ${rewrite!.attempt}/${rewrite!.maxAttempts})`
            : "Rewriting patch..."}
        </span>
      )}
      {rewriteFailed && (
        <span css={rewriteFailedCss}>
          Patch auto-fix failed ({rewrite!.maxAttempts}/{rewrite!.maxAttempts}{" "}
          attempts)
        </span>
      )}
      {rewriteSucceeded && (
        <span css={rewriteSuccessBadgeCss}>Patch auto-corrected</span>
      )}

      {/* Second args section: rewritten args, shown only on success */}
      {rewriteSucceeded && Object.keys(tc.args).length > 0 && (
        <>
          <div css={rewrittenArgsBannerCss}>Rewritten args</div>
          <div css={toolArgsCss}>
            <JsonArgsViewer args={tc.args} />
          </div>
        </>
      )}

      {isStreaming && displayResult !== undefined && (
        <div css={streamingResultCss}>
          <Ansi>{displayResult}</Ansi>
        </div>
      )}
      {hasResult && (
        <div css={isDenied ? deniedToolResultCss : toolResultCss}>
          <Ansi>{displayResult}</Ansi>
        </div>
      )}
    </div>
  );
}
