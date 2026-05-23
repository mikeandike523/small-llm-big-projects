import { useState, Fragment } from "react";
import { css, keyframes } from "@emotion/react";

import { useStickToBottom } from "use-stick-to-bottom";
import type { TodoItem, Turn } from "../types";

import scrollbarCss from "../css/scrollBarCss";
import { TextPresenter } from "./TextPresenter";
import ToolCallCard from "./ToolCallCard";
import ToolApprovalBubble from "./ToolApprovalBubble";

const turnWrapperCss = css`
  display: flex;
  flex-direction: column;
  gap: 0;
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

const turnContainerCss = css`
  display: grid;
  grid-template-columns: 2fr 1.5fr 1fr;
  gap: 24px;
  padding: 20px 24px;
  border: 1px solid #22304d;
  border-radius: 0 0 12px 12px;
  background: #0d131e;
  box-shadow: 0 3px 16px rgba(0, 0, 0, 0.5);
`;
 
const turnContainerNoTitleCss = css`
  display: grid;
  grid-template-columns: 3fr 2.5fr 1.5fr;
  gap: 24px;
  padding: 20px 24px;
  border: 1px solid #22304d;
  border-radius: 12px;
  background: #0d131e;
  box-shadow: 0 3px 16px rgba(0, 0, 0, 0.5);
`;

const leftColumnCss = css`
  ${scrollbarCss}
  overflow-y: auto;
  max-height: 480px;
`;

const leftContentCss = css`
  display: flex;
  flex-direction: column;
  gap: 14px;
  overflow-y: hidden;
`;

// Center column is a sub-grid split into a Thinking section (top, 1fr) and a
// Tool Calls section (bottom, 4.5fr). Each section is independently scrollable
// so scrolling tool calls does not scroll the thinking bubble away.
const centerColumnCss = css`
  display: grid;
  grid-template-rows: minmax(150px, 400px) minmax(200px, 500px);
  max-height: 480px;
  min-height: 0;
  gap: 8px;
`;

const centerSectionHeaderCss = css`
  font-size: 11px;
  color: #e6edff;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-bottom: 4px;
  flex-shrink: 0;
`;

// Top sub-section (Thinking). Owns its own scroll viewport so that scrolling
// tool calls below does not affect what is shown here.
const thinkingSectionCss = css`
  display: flex;
  flex-direction: column;
  min-height: 0;
`;

const thinkingScrollCss = css`
  ${scrollbarCss}
  flex: 1;
  min-height: 0;
  overflow-y: auto;
`;

const thinkingContentCss = css`
  display: flex;
  flex-direction: column;
  gap: 12px;
`;

// Bottom sub-section (Tool Calls). Visually separated from the thinking
// section above by a top border, mirroring the column divider style used
// between the major columns of TurnContainer.
const toolCallsSectionCss = css`
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-top: 1px solid #22304d;
  padding-top: 8px;
`;

const toolCallsScrollCss = css`
  ${scrollbarCss}
  flex: 1;
  min-height: 0;
  overflow-y: auto;
`;

const toolCallsContentCss = css`
  display: flex;
  flex-direction: column;
  gap: 12px;
`;

const todoColumnCss = css`
  ${scrollbarCss}
  display: flex;
  flex-direction: column;
  gap: 4px;
  border-left: 1px solid #22304d;
  padding-left: 16px;
  min-width: 0;
  overflow-y: auto;
  max-height: 480px;
`;

const todoHeaderCss = css`
  font-size: 11px;
  color: #e6edff;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-bottom: 4px;
`;

const todoEmptyCss = css`
  font-size: 12px;
  color: #dbe5ff;
  font-style: italic;
`;

const approvalRowCss = css`
  grid-column: 1 / -1;
  display: flex;
  flex-direction: column;
  gap: 8px;
  border-top: 1px solid #22304d;
  padding-top: 16px;
  min-height: 120px;
`;

// Inner 3-column grid for the approval/questions row
const approvalInnerGridCss = css`
  display: grid;
  grid-template-columns: 150px 1.2fr;
  min-height: 100px;
`;

// Base for each column inside the grid
const approvalCol1Css = css`
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 0 14px 4px 2px;
  min-width: 0;
  min-height: 0;
`;

const approvalCol2Css = css`
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 0 14px 4px 14px;
  border-left: 1px solid #22304d;
  min-width: 0;
`;


const approvalColHeaderCss = css`
  font-size: 10px;
  color: #e6edff;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  font-family: "Consolas", monospace;
  margin-bottom: 4px;
  flex-shrink: 0;
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
  max-height: 180px;
  overflow-y: auto;
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

const interruptedBubbleCss = css`
  background: #1a1020;
  border: 1px solid #4a2a6a;
  border-radius: 8px;
  padding: 6px 12px;
  font-size: 11px;
  color: #d5b8ff;
  font-style: italic;
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

// Compaction detail modal
const compactionModalOverlayCss = css`
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.75);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
`;

const compactionModalCss = css`
  background: #0e0e14;
  border: 1px solid #7a2545;
  border-radius: 12px;
  padding: 20px 24px;
  max-width: 680px;
  width: 90%;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  gap: 12px;
`;

const compactionModalTitleCss = css`
  font-size: 13px;
  font-weight: 600;
  color: #c87090;
`;

const compactionModalBodyCss = css`
  font-size: 12px;
  color: #d4a8b8;
  white-space: pre-wrap;
  word-break: break-word;
  overflow-y: auto;
  flex: 1;
  line-height: 1.6;
`;

const compactionModalCloseCss = css`
  background: #2a0d20;
  border: 1px solid #7a2545;
  border-radius: 6px;
  color: #c87090;
  font-size: 12px;
  padding: 6px 14px;
  cursor: pointer;
  align-self: flex-end;
  &:hover {
    background: #3a1030;
  }
`;

const reasoningWrapperCss = css`
  color: #7aa2e0;
  font-size: 13px;
  font-style: italic;
  background: #111827;
  border: 1px solid #1e3a5f;
  border-radius: 10px;
  padding: 12px 16px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
`;

const iratThinkingWrapperCss = css`
  color: #c49a4a;
  font-size: 13px;
  font-style: italic;
  background: #1a1408;
  border: 1px solid #4a360f;
  border-radius: 10px;
  padding: 12px 16px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
`;

const thinkingAnimWrapCss = css`
  display: grid;
  transition: grid-template-rows 0.3s ease-out, opacity 0.25s ease-out;
`;

const thinkingAnimInnerCss = css`
  overflow: hidden;
`;

const thinkingBubbleLabelCss = css`
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  font-family: "Consolas", monospace;
  font-style: normal;
  margin-bottom: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid;
  opacity: 0.8;
`;

// Same layout as toolCallsGroupCss but without its own scroll — for use inside
// a column that is itself the scroll viewport (see TurnContainer right column).
const toolCallsGroupInnerCss = css`
  display: flex;
  flex-direction: column;
  gap: 10px;
`;

const subturnDividerCss = css`
  font-size: 10px;
  color: #3a4d6e;
  text-align: center;
  padding: 2px 0;
  border-top: 1px solid #1e2d45;
  margin: 2px 0;
  letter-spacing: 0.04em;
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

// Col 1: outcome chips
const outcomesScrollCss = css`
  ${scrollbarCss}
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  max-height: 200px;
  padding-right: 4px;
`;

const approvalListContentCss = (gap: number) => css`
  display: flex;
  flex-direction: column;
  gap: ${gap}px;
`;

const outcomeApprovalChipCss = (approved: boolean) => css`
  font-family: "Consolas", monospace;
  font-size: 11px;
  color: ${approved ? "#4ade80" : "#f87171"};
  background: ${approved ? "#071207" : "#120707"};
  border: 1px solid ${approved ? "#14532d" : "#450a0a"};
  border-radius: 3px;
  padding: 2px 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
`;

// Col 2: active dialog placeholder (nothing pending)
const activeDialogPlaceholderCss = css`
  font-size: 12px;
  color: #dbe5ff;
  font-style: italic;
  font-family: "Consolas", monospace;
`;

const todoItemOpenCss = css`
  font-size: 12px;
  color: #c0c0c0;
  font-family: "Consolas", monospace;
  padding: 2px 0;
  white-space: nowrap;
`;

const todoItemClosedCss = css`
  font-size: 12px;
  color: #505050;
  font-family: "Consolas", monospace;
  padding: 2px 0;
  text-decoration: line-through;
  white-space: nowrap;
`;

function stripMdExtension(s: string): string {
  return s.endsWith(".md") ? s.slice(0, -3) : s;
}

function renderTodoItems(
  items: TodoItem[],
  depth: number = 0,
): React.ReactNode[] {
  return items.flatMap((item) => {
    const pathStr = item.item_path + ".";
    const rows: React.ReactNode[] = [
      <div
        key={pathStr}
        css={item.status === "closed" ? todoItemClosedCss : todoItemOpenCss}
        style={{ paddingLeft: depth * 14 }}
        title={item.text}
      >
        {pathStr} {item.text}
      </div>,
    ];
    if (item.children && item.children.length > 0) {
      rows.push(...renderTodoItems(item.children, depth + 1));
    }
    return rows;
  });
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
  onApprove: (id: string) => void;
  onDeny: (id: string) => void;
  onDenyWithRedirect: (id: string, message: string) => void;
  onDenyAndStop: (id: string) => void;
}) {
  const [compactionModalSubturnId, setCompactionModalSubturnId] = useState<
    string | null
  >(null);

  const {
    todoItems,
    approvalItems,
    impossible,
    subturns,
    streaming,
    isInterimStreaming,
    interimShowCharCount,
    interimCharCount,
    interrupted,
  } = turn;

  const { scrollRef: leftScrollRef, contentRef: leftContentRef } =
    useStickToBottom();
  const { scrollRef: thinkingScrollRef, contentRef: thinkingContentRef } =
    useStickToBottom();
  const { scrollRef: toolsScrollRef, contentRef: toolsContentRef } =
    useStickToBottom();
  const { scrollRef: todoScrollRef, contentRef: todoContentRef } =
    useStickToBottom();
  const { scrollRef: outcomesScrollRef, contentRef: outcomesContentRef } =
    useStickToBottom();
  const hasPendingApproval = approvalItems.some((a) => !a.resolved);
  const resolvedApprovals = approvalItems.filter((a) => a.resolved);
  const pendingApprovals = approvalItems.filter((a) => !a.resolved);

  const lastSubturn = subturns[subturns.length - 1];
  const lastSubturnExchanges = lastSubturn?.exchanges ?? [];

  // Collect tool call groups from ALL subturns (right column — grows as subturns are added)
  const toolCallGroups = subturns
    .map((st, idx) => ({
      subturnIdx: idx,
      subturnId: st.id,
      toolCalls: st.exchanges.flatMap((ex) => ex.toolCalls),
    }))
    .filter((g) => g.toolCalls.length > 0);
  const hasMultipleToolGroups = toolCallGroups.length > 1;
  const totalToolCallCount = toolCallGroups.reduce(
    (n, g) => n + g.toolCalls.length,
    0,
  );

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

  // Reasoning from the current (last) exchange only — resets naturally each LLM call
  const reasoning = lastExchange?.reasoning ?? "";

  // IRAT thinking: only the current (last) exchange — resets naturally each LLM call
  const iratThinking =
    lastSubturnExchanges[lastSubturnExchanges.length - 1]?.iratThinking ?? "";

  const isStreamingFinal = streaming && !isInterimStreaming;
  const showPlaceholder =
    streaming &&
    !displayContent &&
    !isInterimStreaming &&
    totalToolCallCount === 0;

  const hasBanner = !!turn.taskTitle || (turn.loadedSkills?.length ?? 0) > 0;

  return (
    <div css={turnWrapperCss}>
      {hasBanner ? (
        <div css={turnBannerCss}>
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
      ) : null}
      <div css={hasBanner ? turnContainerCss : turnContainerNoTitleCss}>
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
                        maxHeight={isLast ? 600 : 300}
                        streaming={isLast && isStreamingFinal}
                      />
                    </div>
                  ) : isLast && showPlaceholder ? (
                    <div css={streamingPlaceholderCss}>…</div>
                  ) : null}
                  {(() => {
                    if (!st.detailedSummary) return null;
                    if (isLast && streaming) return null;
                    const summary = st.detailedSummary;
                    const previewText =
                      summary.slice(0, 200) + (summary.length > 200 ? "…" : "");
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
            {interrupted && (
              <div css={interruptedBubbleCss}>Connection interrupted</div>
            )}
          </div>
        </div>

        {/* Center column: sub-grid split into a Thinking section (top, 1fr)
            and a Tool Calls section (bottom, 4.5fr). Each section has its
            own scroll viewport so that scrolling tool calls does not push
            the thinking bubble away. */}
        <div css={centerColumnCss}>
          {/* Top sub-section: Thinking (reasoning + irat thinking) */}
          <div css={thinkingSectionCss}>
            <div css={centerSectionHeaderCss}>Thinking</div>
            <div css={thinkingScrollCss} ref={thinkingScrollRef}>
              <div css={thinkingContentCss} ref={thinkingContentRef}>
                <div
                  css={thinkingAnimWrapCss}
                  style={{ gridTemplateRows: reasoning ? "1fr" : "0fr", opacity: reasoning ? 1 : 0 }}
                >
                  <div css={thinkingAnimInnerCss}>
                    <div css={reasoningWrapperCss}>
                      <div css={thinkingBubbleLabelCss} style={{ color: "#7aa2e0", borderBottomColor: "#1e3a5f" }}>
                        Native Thinking
                      </div>
                      <TextPresenter
                        content={reasoning}
                        maxHeight={200}
                        streaming={streaming}
                        initialMode="plain"
                        showToggle={false}
                      />
                    </div>
                  </div>
                </div>
                <div
                  css={thinkingAnimWrapCss}
                  style={{ gridTemplateRows: iratThinking ? "1fr" : "0fr", opacity: iratThinking ? 1 : 0 }}
                >
                  <div css={thinkingAnimInnerCss}>
                    <div css={iratThinkingWrapperCss}>
                      <div css={thinkingBubbleLabelCss} style={{ color: "#c49a4a", borderBottomColor: "#4a360f" }}>
                        IRAT Thinking
                      </div>
                      <TextPresenter
                        content={iratThinking}
                        maxHeight={200}
                        streaming={streaming}
                        initialMode="plain"
                        showToggle={false}
                      />
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Bottom sub-section: Tool Calls */}
          <div css={toolCallsSectionCss}>
            <div css={centerSectionHeaderCss}>Tool Calls</div>
            <div css={toolCallsScrollCss} ref={toolsScrollRef}>
              <div css={toolCallsContentCss} ref={toolsContentRef}>
                {totalToolCallCount > 0 && (
                  <div css={toolCallsGroupInnerCss}>
                    {toolCallGroups.map((group) => (
                      <Fragment key={group.subturnId}>
                        {hasMultipleToolGroups && (
                          <div css={subturnDividerCss}>
                            subturn {group.subturnIdx + 1}
                          </div>
                        )}
                        {group.toolCalls.map((tc) => (
                          <ToolCallCard
                            key={tc.id}
                            tc={tc}
                            onViewFull={onViewFull}
                          />
                        ))}
                      </Fragment>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Third column: todo list */}
        <div css={todoColumnCss} ref={todoScrollRef}>
          <div css={todoHeaderCss}>Todo</div>
          <div ref={todoContentRef}>
            {todoItems.length === 0 ? (
              <div css={todoEmptyCss}>empty</div>
            ) : (
              renderTodoItems(todoItems)
            )}
          </div>
        </div>

        {/* Full-width bottom row: approval panel */}
        {approvalItems.length > 0 && (
          <div css={approvalRowCss}>
            <div css={approvalInnerGridCss}>
              {/* Col 1: Resolved approval chips, grouped by subturn */}
              <div css={approvalCol1Css}>
                <div css={approvalColHeaderCss}>Outcomes</div>
                {resolvedApprovals.length === 0 ? (
                  <div css={activeDialogPlaceholderCss}>—</div>
                ) : (
                  <div css={outcomesScrollCss} ref={outcomesScrollRef}>
                    <div
                      ref={outcomesContentRef}
                      css={approvalListContentCss(3)}
                    >
                      {(() => {
                        // Group consecutive resolved approvals by subturnId for dividers
                        const groups: {
                          subturnId: string | undefined;
                          items: typeof resolvedApprovals;
                        }[] = [];
                        for (const item of resolvedApprovals) {
                          const last = groups[groups.length - 1];
                          if (last && last.subturnId === item.subturnId) {
                            last.items.push(item);
                          } else {
                            groups.push({
                              subturnId: item.subturnId,
                              items: [item],
                            });
                          }
                        }
                        const showDividers = groups.length > 1;
                        return groups.map((group, gIdx) => (
                          <Fragment key={group.subturnId ?? gIdx}>
                            {showDividers && (
                              <div css={subturnDividerCss}>
                                {group.subturnId
                                  ? `subturn ${subturns.findIndex((st) => st.id === group.subturnId) + 1}`
                                  : `group ${gIdx + 1}`}
                              </div>
                            )}
                            {group.items.map((item) => (
                              <div
                                key={item.id}
                                css={outcomeApprovalChipCss(
                                  item.resolved!.approved,
                                )}
                                title={item.tool_name}
                              >
                                {item.resolved!.approved ? "✓" : "✗"}{" "}
                                {item.tool_name}
                              </div>
                            ))}
                          </Fragment>
                        ));
                      })()}
                    </div>
                  </div>
                )}
              </div>

              {/* Col 2: Active approval dialogs */}
              <div css={approvalCol2Css}>
                {hasPendingApproval ? (
                  <div css={approvalColHeaderPendingCss}>⚠ Approval Needed</div>
                ) : (
                  <div css={approvalColHeaderCss}>Active</div>
                )}
                {pendingApprovals.length === 0 ? (
                  <div css={activeDialogPlaceholderCss}>—</div>
                ) : (
                  <>
                    {pendingApprovals.map((item) => (
                      <ToolApprovalBubble
                        key={item.id}
                        item={item}
                        onApprove={onApprove}
                        onDeny={onDeny}
                        onDenyWithRedirect={onDenyWithRedirect}
                        onDenyAndStop={onDenyAndStop}
                      />
                    ))}
                  </>
                )}
              </div>

            </div>
          </div>
        )}
      </div>
      {compactionModalSubturnId &&
        (() => {
          const st = subturns.find((s) => s.id === compactionModalSubturnId);
          if (!st?.detailedSummary) return null;
          return (
            <div
              css={compactionModalOverlayCss}
              onClick={() => setCompactionModalSubturnId(null)}
            >
              <div
                css={compactionModalCss}
                onClick={(e) => e.stopPropagation()}
              >
                <div css={compactionModalTitleCss}>Context Notes</div>
                <div css={compactionModalBodyCss}>{st.detailedSummary}</div>
                <button
                  css={compactionModalCloseCss}
                  onClick={() => setCompactionModalSubturnId(null)}
                >
                  Close
                </button>
              </div>
            </div>
          );
        })()}
    </div>
  );
}
