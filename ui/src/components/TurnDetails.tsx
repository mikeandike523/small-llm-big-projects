import { useRef } from "react";
import { css } from "@emotion/react";
import { useStickToBottom } from "use-stick-to-bottom";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { TodoItem, Turn, ToolCallEntry } from "../types";

import scrollbarCss from "../css/scrollBarCss";
import {
  autoScrollShineCss,
  SHINE_HEIGHT_TOOL_CALLS_PX,
} from "../css/autoScrollShineCss";
import { TextPresenter } from "./TextPresenter";
import ToolCallCard from "./ToolCallCard";
import {
  estimateDividerHeight,
  estimateToolCallCardHeight,
} from "../estimators/tool-call-bubble";
import { useStickToEnd } from "../hooks/useStickToEnd";

// Fallback column width for the very first render, before toolsScrollRef has
// mounted and clientWidth is available. The column is fully responsive
// (grid fr units), so there's no "real" static value — this only matters
// for the first paint's estimate, since every render after mount reads the
// actual width.
const FALLBACK_TOOL_CALLS_COLUMN_WIDTH_PX = 340;

// Center column is a sub-grid split into a Thinking section (top, 1fr) and a
// Tool Calls section (bottom, 4.5fr). Each section is independently scrollable
// so scrolling tool calls does not scroll the thinking bubble away.
const centerColumnCss = css`
  display: grid;
  grid-template-rows: minmax(0, 4fr) minmax(0, 5fr);
  min-height: 0;
  min-width: 0;
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
  min-width: 0;
`;

const thinkingScrollCss = css`
  ${scrollbarCss}
  flex: 1;
  min-height: 0;
  min-width: 0;
  overflow-y: auto;
  overflow-x: hidden;
`;

const thinkingContentCss = css`
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
`;

// Bottom sub-section (Tool Calls). Visually separated from the thinking
// section above by a top border, mirroring the column divider style used
// between the major columns of TurnContainer.
const toolCallsSectionCss = css`
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
  border-top: 1px solid #22304d;
  padding-top: 8px;
`;

// Wraps the scroll viewport so the autoscroll shine below can be pinned to
// the visible bottom edge without scrolling away with the content.
const toolCallsViewportCss = css`
  position: relative;
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  min-width: 0;
`;

const toolCallsScrollCss = css`
  ${scrollbarCss}
  flex: 1;
  min-height: 0;
  min-width: 0;
  overflow-y: auto;
  overflow-x: hidden;
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
  min-height: 0;
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
  transition:
    grid-template-rows 0.3s ease-out,
    opacity 0.25s ease-out;
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

const subturnDividerCss = css`
  font-size: 10px;
  color: #3a4d6e;
  text-align: center;
  padding: 2px 0;
  border-top: 1px solid #1e2d45;
  margin: 2px 0;
  letter-spacing: 0.04em;
`;

const todoItemOpenCss = css`
  font-size: 12px;
  color: #c0c0c0;
  font-family: "Consolas", monospace;
  padding: 2px 0;
  white-space: pre-wrap;
`;

const todoItemClosedCss = css`
  font-size: 12px;
  color: #505050;
  font-family: "Consolas", monospace;
  padding: 2px 0;
  text-decoration: line-through;
  white-space: pre-wrap;
`;

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

/**
 * A turn's Thinking / Tool Calls and Todo columns (two grid items placed in
 * TurnContainer's grid). Mounted only while the turn's Details are expanded,
 * so collapsed turns run none of this rendering or virtualization.
 */
export default function TurnDetails({
  turn,
  onViewFull,
}: {
  turn: Turn;
  onViewFull: (content: string) => void;
}) {
  const { subturns, todoItems, streaming } = turn;

  const { scrollRef: thinkingScrollRef, contentRef: thinkingContentRef } =
    useStickToBottom();
  const toolsScrollRef = useRef<HTMLDivElement>(null);
  const { scrollRef: todoScrollRef, contentRef: todoContentRef } =
    useStickToBottom();

  const lastSubturnExchanges = subturns[subturns.length - 1]?.exchanges ?? [];
  const lastExchange = lastSubturnExchanges[lastSubturnExchanges.length - 1];

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

  // Flatten groups (dividers + cards) into one row list for the virtualizer —
  // only this column is virtualized: a single turn's tool calls can grow
  // unbounded across a long agentic loop, whereas the number of turns
  // themselves is a session-level concern (better solved by compaction than
  // by nesting a second virtualizer around TurnContainer itself).
  type ToolCallRow =
    | { type: "divider"; key: string; subturnIdx: number }
    | { type: "card"; key: string; tc: ToolCallEntry };
  const toolCallRows: ToolCallRow[] = [];
  for (const group of toolCallGroups) {
    if (hasMultipleToolGroups) {
      toolCallRows.push({
        type: "divider",
        key: `divider:${group.subturnId}`,
        subturnIdx: group.subturnIdx,
      });
    }
    for (const tc of group.toolCalls) {
      toolCallRows.push({ type: "card", key: tc.id, tc });
    }
  }

  const estimateToolCallRowSize = (index: number): number => {
    const row = toolCallRows[index];
    if (row.type === "divider") return estimateDividerHeight();
    const availableWidthPx =
      toolsScrollRef.current?.clientWidth ??
      FALLBACK_TOOL_CALLS_COLUMN_WIDTH_PX;
    return estimateToolCallCardHeight(row.tc, availableWidthPx);
  };

  const toolCallsVirtualizer = useVirtualizer({
    count: toolCallRows.length,
    getScrollElement: () => toolsScrollRef.current,
    estimateSize: estimateToolCallRowSize,
    getItemKey: (index) => toolCallRows[index].key,
    overscan: 5,
  });
  const isToolCallsAutoScrolling = useStickToEnd(toolCallsVirtualizer);

  // Reasoning from the current (last) exchange only — resets naturally each LLM call
  const reasoning = lastExchange?.reasoning ?? "";

  // IRAT thinking: only the current (last) exchange — resets naturally each LLM call
  const iratThinking =
    lastSubturnExchanges[lastSubturnExchanges.length - 1]?.iratThinking ?? "";

  return (
    <>
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
                style={{
                  gridTemplateRows: reasoning ? "1fr" : "0fr",
                  opacity: reasoning ? 1 : 0,
                }}
              >
                <div css={thinkingAnimInnerCss}>
                  <div css={reasoningWrapperCss}>
                    <div
                      css={thinkingBubbleLabelCss}
                      style={{
                        color: "#7aa2e0",
                        borderBottomColor: "#1e3a5f",
                      }}
                    >
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
                style={{
                  gridTemplateRows: iratThinking ? "1fr" : "0fr",
                  opacity: iratThinking ? 1 : 0,
                }}
              >
                <div css={thinkingAnimInnerCss}>
                  <div css={iratThinkingWrapperCss}>
                    <div
                      css={thinkingBubbleLabelCss}
                      style={{
                        color: "#c49a4a",
                        borderBottomColor: "#4a360f",
                      }}
                    >
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
          <div css={toolCallsViewportCss}>
            <div css={toolCallsScrollCss} ref={toolsScrollRef}>
              {totalToolCallCount > 0 && (
                <div
                  style={{
                    position: "relative",
                    width: "100%",
                    height: toolCallsVirtualizer.getTotalSize(),
                  }}
                >
                  {toolCallsVirtualizer.getVirtualItems().map((virtualRow) => {
                    const row = toolCallRows[virtualRow.index];
                    return (
                      <div
                        key={row.key}
                        data-index={virtualRow.index}
                        ref={toolCallsVirtualizer.measureElement}
                        style={{
                          position: "absolute",
                          top: 0,
                          left: 0,
                          width: "100%",
                          paddingBottom: 12,
                          transform: `translateY(${virtualRow.start}px)`,
                        }}
                      >
                        {row.type === "divider" ? (
                          <div css={subturnDividerCss}>
                            subturn {row.subturnIdx + 1}
                          </div>
                        ) : (
                          <ToolCallCard tc={row.tc} onViewFull={onViewFull} />
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
            <div
              css={autoScrollShineCss(
                isToolCallsAutoScrolling,
                SHINE_HEIGHT_TOOL_CALLS_PX,
              )}
            />
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
    </>
  );
}
