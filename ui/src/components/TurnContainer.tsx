import { useState, Fragment } from "react";
import { css, keyframes } from "@emotion/react";
import { FaHeartbeat, FaUser } from "react-icons/fa";

import { useStickToBottom } from "use-stick-to-bottom";
import type { SubturnOrigin, Turn } from "../types";

import scrollbarCss from "../css/scrollBarCss";
import { TextPresenter } from "./TextPresenter";
import ToolApprovalBubble from "./ToolApprovalBubble";
import PanelDivider from "./PanelDivider";
import TurnDetails from "./TurnDetails";
import SubturnStatsPills from "../subcomponents/TurnContainer/SubturnStatsPills";
import ContextNotesModal from "../subcomponents/TurnContainer/ContextNotesModal";

// A turn fills its page: banner on top, body takes the remaining height.
const turnWrapperCss = css`
  display: flex;
  flex-direction: column;
  gap: 0;
  height: 100%;
  min-height: 0;
`;

const turnBannerCss = css`
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  font-family: "Consolas", monospace;
  background: #0d180d;
  border: 1px solid #1e3a1e;
  border-bottom: none;
  border-radius: 8px 8px 0 0;
  padding: 5px 16px;
  flex-shrink: 0;
`;

const taskTitleCss = css`
  font-size: 11px;
  color: #6a9a6a;
  letter-spacing: 0.04em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
  flex: 1;
`;

const skillPillsRowCss = css`
  display: flex;
  gap: 5px;
  flex-shrink: 0;
  align-items: center;
`;

const skillPillCss = css`
  font-size: 10px;
  color: #5090c0;
  background: #0d1a2d;
  border: 1px solid #1e3a5a;
  border-radius: 10px;
  padding: 2px 8px;
  letter-spacing: 0.03em;
  white-space: nowrap;
`;

const ownerPillBaseCss = css`
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  font-size: 10px;
  border-radius: 10px;
  padding: 2px 8px;
  letter-spacing: 0.03em;
  white-space: nowrap;
`;

const ownerPillCss: Record<SubturnOrigin, ReturnType<typeof css>> = {
  user: css`
    ${ownerPillBaseCss};
    color: #8ab88a;
    background: #102010;
    border: 1px solid #2a4a2a;
  `,
  heartbeat: css`
    ${ownerPillBaseCss};
    color: #e06c6c;
    background: #2a0d0d;
    border: 1px solid #5a1e1e;
  `,
};

const OWNER_PILL_LABEL: Record<SubturnOrigin, string> = {
  user: "Human",
  heartbeat: "Heartbeat",
};

// The turn body: the column grid plus, on the right edge, the "Details"
// divider that collapses the Thinking/Tool Calls and Todo columns.
const turnBodyCss = css`
  flex: 1;
  min-height: 0;
  display: flex;
  border: 1px solid #22304d;
  border-radius: 0 0 12px 12px;
  background: #0d131e;
  box-shadow: 0 3px 16px rgba(0, 0, 0, 0.5);
  overflow: hidden;
`;

const turnGridCss = (expanded: boolean) => css`
  flex: 1;
  min-width: 0;
  display: grid;
  grid-template-columns: ${expanded
    ? "minmax(0, 5fr) minmax(0, 4fr) minmax(0, 2fr)"
    : "minmax(0, 1fr)"};
  /* Columns fill the height; pending approvals take an auto row below. */
  grid-template-rows: minmax(0, 1fr);
  min-height: 0;
  gap: 24px;
  padding: 20px 24px;
`;

const leftColumnCss = css`
  ${scrollbarCss}
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
`;

const leftContentCss = css`
  display: flex;
  flex-direction: column;
  gap: 14px;
  overflow-y: hidden;
`;

const approvalRowCss = css`
  grid-column: 1 / -1;
  display: flex;
  flex-direction: column;
  gap: 8px;
  border-top: 1px solid #22304d;
  padding-top: 16px;
  max-height: 45vh;
  overflow-y: auto;
  ${scrollbarCss}
`;

const userBubbleCss = css`
  ${scrollbarCss}
  background: #1d4ed8;
  border: 1px solid #2d5fe8;
  border-radius: 16px 16px 4px 16px;
  padding: 12px 16px;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.5;
  align-self: flex-end;
  box-shadow: 0 2px 10px rgba(29, 78, 216, 0.3);
`;

const assistantBubbleCss = css`
  background: #111827;
  border: 1px solid #283754;
  border-radius: 16px 16px 16px 4px;
  padding: 12px 16px;
  word-break: break-word;
  line-height: 1.5;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.35);
`;

const streamingPlaceholderCss = css`
  background: #111827;
  border: 1px solid #283754;
  border-radius: 16px 16px 16px 4px;
  padding: 12px 16px;
  color: #dbe5ff;
`;

const emptyResponseCss = css`
  background: #111827;
  border: 1px solid #283754;
  border-radius: 16px 16px 16px 4px;
  padding: 12px 16px;
  color: #5a6a8a;
  font-style: italic;
  font-size: 13px;
`;

const interimBubbleCss = css`
  background: #0f1726;
  border: 1px solid #24324d;
  border-radius: 8px;
  padding: 5px 10px;
  font-size: 11px;
  color: #d6e0f5;
  font-family: "Consolas", monospace;
  font-style: italic;
`;

const impossibleBubbleCss = css`
  background: #1a0a00;
  border: 1px solid #7a3000;
  border-radius: 10px;
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
  gap: 4px;
`;

const impossibleLabelCss = css`
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: #c05010;
  font-weight: 600;
`;

const impossibleReasonCss = css`
  font-size: 13px;
  color: #d08040;
  line-height: 1.5;
  word-break: break-word;
`;

// Mini compaction bubble (appears below assistant response when detailed_summary is available)
const compactionBubbleCss = css`
  background: #1a0815;
  border: 1px solid #7a2545;
  border-radius: 10px;
  padding: 8px 12px;
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-top: 4px;
`;

const compactionTextCss = css`
  font-size: 11px;
  color: #c87090;
  flex: 1;
  font-style: italic;
  overflow: hidden;
  white-space: pre-wrap;
  word-break: break-word;
`;

const compactionDetailsButtonCss = css`
  background: none;
  border: 1px solid #7a2545;
  border-radius: 4px;
  color: #c87090;
  font-size: 10px;
  padding: 2px 6px;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
  &:hover {
    background: #2a0d20;
  }
`;

const _approvalColHeaderPulse = keyframes`
  0%, 100% { color: #a07030; }
  50%       { color: #d4a030; }
`;

const approvalColHeaderPendingCss = css`
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  font-family: "Consolas", monospace;
  margin-bottom: 4px;
  flex-shrink: 0;
  font-weight: 600;
  animation: ${_approvalColHeaderPulse} 1.8s ease-in-out infinite;
`;

function stripMdExtension(s: string): string {
  return s.endsWith(".md") ? s.slice(0, -3) : s;
}

export default function TurnContainer({
  turn,
  onViewFull,
  onApprove,
  onDeny,
  onDenyWithRedirect,
  onDenyAndStop,
}: {
  turn: Turn;
  onViewFull: (content: string) => void;
  onApprove: (id: string, turnId: string) => void;
  onDeny: (id: string, turnId: string) => void;
  onDenyWithRedirect: (id: string, turnId: string, message: string) => void;
  onDenyAndStop: (id: string, turnId: string) => void;
}) {
  const [compactionModalSubturnId, setCompactionModalSubturnId] = useState<
    string | null
  >(null);
  // Every turn starts collapsed; Details shows Thinking/Tool Calls and Todo.
  const [expanded, setExpanded] = useState(false);

  const {
    todoItems,
    approvalItems,
    impossible,
    subturns,
    streaming,
    isInterimStreaming,
    interimShowCharCount,
    interimCharCount,
  } = turn;

  const { scrollRef: leftScrollRef, contentRef: leftContentRef } =
    useStickToBottom();
  // Resolved approvals are dropped from state; only pending ones remain.
  const pendingApprovals = approvalItems;
  const totalToolCallCount = subturns.reduce(
    (n, st) => n + st.exchanges.reduce((m, ex) => m + ex.toolCalls.length, 0),
    0,
  );

  const lastSubturn = subturns[subturns.length - 1];
  const lastSubturnExchanges = lastSubturn?.exchanges ?? [];

  // Display content for the current/last subturn: final exchange or live streaming
  const lastExchange = lastSubturnExchanges[lastSubturnExchanges.length - 1];
  const finalExchange = lastSubturnExchanges.find((ex) => ex.isFinal);
  const liveContent =
    streaming &&
    !isInterimStreaming &&
    lastExchange &&
    !lastExchange.isFinal &&
    lastExchange.toolCalls.length === 0
      ? lastExchange.assistantContent
      : undefined;
  const displayContent = finalExchange?.assistantContent ?? liveContent ?? "";

  const isStreamingFinal = streaming && !isInterimStreaming;
  const showPlaceholder =
    streaming &&
    !displayContent &&
    !isInterimStreaming &&
    totalToolCallCount === 0;

  // The turn's current owner is whoever started its latest subturn.
  const owner: SubturnOrigin =
    turn.subturns[turn.subturns.length - 1]?.origin ?? "user";

  return (
    <div css={turnWrapperCss}>
      <div css={turnBannerCss}>
        <span
          css={ownerPillCss[owner]}
          title={
            owner === "heartbeat"
              ? "Started by a heartbeat"
              : "Started by a human"
          }
        >
          {owner === "heartbeat" ? (
            <FaHeartbeat size={9} />
          ) : (
            <FaUser size={9} />
          )}
          {OWNER_PILL_LABEL[owner]}
        </span>
        <span css={taskTitleCss}>
          {turn.taskTitle ? `Task: ${turn.taskTitle}` : ""}
        </span>
        {turn.loadedSkills && turn.loadedSkills.length > 0 && (
          <div css={skillPillsRowCss}>
            {turn.loadedSkills.map((skillName) => (
              <span key={skillName} css={skillPillCss}>
                {stripMdExtension(skillName)}
              </span>
            ))}
          </div>
        )}
      </div>
      <div css={turnBodyCss}>
        <div css={turnGridCss(expanded)}>
          {/* Left column: user message(s) + AI content — one bubble-group per subturn */}
          <div css={leftColumnCss} ref={leftScrollRef}>
            <div css={leftContentCss} ref={leftContentRef}>
              {subturns.map((st, stIdx) => {
                const isLast = stIdx === subturns.length - 1;
                const stFinal = st.exchanges.find((ex) => ex.isFinal);
                const stContent = isLast
                  ? displayContent
                  : (stFinal?.assistantContent ?? "");
                return (
                  <Fragment key={st.id}>
                    <div css={userBubbleCss}>{st.userText}</div>
                    <SubturnStatsPills
                      subturn={st}
                      todoItems={isLast ? todoItems : undefined}
                    />
                    {isLast &&
                      interimShowCharCount &&
                      (interimCharCount > 0 || isInterimStreaming) && (
                        <div css={interimBubbleCss}>
                          AI interim response: {interimCharCount} chars
                        </div>
                      )}
                    {stContent ? (
                      <div
                        css={assistantBubbleCss}
                        style={!isLast ? { opacity: 0.7 } : undefined}
                      >
                        <TextPresenter
                          content={stContent}
                          streaming={isLast && isStreamingFinal}
                        />
                      </div>
                    ) : isLast && showPlaceholder ? (
                      <div css={streamingPlaceholderCss}>…</div>
                    ) : (isLast ? !streaming : stFinal !== undefined) ? (
                      <div css={emptyResponseCss}>(no response)</div>
                    ) : null}
                    {(() => {
                      if (!st.detailedSummary) return null;
                      if (isLast && streaming) return null;
                      const summary = st.detailedSummary;
                      const previewText =
                        summary.slice(0, 200) +
                        (summary.length > 200 ? "…" : "");
                      return (
                        <div css={compactionBubbleCss}>
                          <span css={compactionTextCss}>{previewText}</span>
                          <button
                            css={compactionDetailsButtonCss}
                            onClick={() => setCompactionModalSubturnId(st.id)}
                          >
                            Details
                          </button>
                        </div>
                      );
                    })()}
                  </Fragment>
                );
              })}
              {impossible ? (
                <div css={impossibleBubbleCss}>
                  <span css={impossibleLabelCss}>Task impossible</span>
                  <span css={impossibleReasonCss}>{impossible}</span>
                </div>
              ) : null}
            </div>
          </div>

          {expanded && <TurnDetails turn={turn} onViewFull={onViewFull} />}

          {/* Full-width bottom row: pending approvals (shown even when collapsed) */}
          {pendingApprovals.length > 0 && (
            <div css={approvalRowCss}>
              <div css={approvalColHeaderPendingCss}>⚠ Approval Needed</div>
              {pendingApprovals.map((item) => (
                <ToolApprovalBubble
                  key={item.id}
                  item={item}
                  onApprove={(id) => onApprove(id, turn.id)}
                  onDeny={(id) => onDeny(id, turn.id)}
                  onDenyWithRedirect={(id, message) =>
                    onDenyWithRedirect(id, turn.id, message)
                  }
                  onDenyAndStop={(id) => onDenyAndStop(id, turn.id)}
                />
              ))}
            </div>
          )}
        </div>
        <PanelDivider
          open={expanded}
          onToggle={() => setExpanded((v) => !v)}
          label="Details"
          side="right"
        />
      </div>
      {compactionModalSubturnId &&
        (() => {
          const st = subturns.find((s) => s.id === compactionModalSubturnId);
          if (!st?.detailedSummary) return null;
          return (
            <ContextNotesModal
              text={st.detailedSummary}
              onClose={() => setCompactionModalSubturnId(null)}
            />
          );
        })()}
    </div>
  );
}
