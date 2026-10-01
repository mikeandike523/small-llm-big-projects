import { css } from "@emotion/react";
import { FaBrain, FaListUl, FaWrench } from "react-icons/fa";
import type { Subturn, TodoItem } from "../../types";

const rowCss = css`
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 5px;
  margin-top: -8px;
`;

const pillCss = css`
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-family: "Consolas", monospace;
  font-size: 10px;
  color: #9fb3d9;
  background: #0f1726;
  border: 1px solid #24324d;
  border-radius: 10px;
  padding: 2px 8px;
  white-space: nowrap;
`;

// CSS can't group digits, so format in JS: 1234567 -> "1,234,567".
function withCommas(n: number): string {
  return n.toLocaleString("en-US");
}

function plural(n: number, word: string): string {
  return `${withCommas(n)} ${word}${n === 1 ? "" : "s"}`;
}

/**
 * Small at-a-glance stats under a subturn's user message, so progress is
 * visible while the turn's Details are collapsed: tool calls, thinking chars
 * (native + IRAT), and, for the latest subturn, top-level todo items closed.
 */
export default function SubturnStatsPills({
  subturn,
  todoItems,
}: {
  subturn: Subturn;
  /** The turn's todo list; passed only for the latest subturn. */
  todoItems?: TodoItem[];
}) {
  const toolCalls = subturn.exchanges.reduce(
    (n, ex) => n + ex.toolCalls.length,
    0,
  );
  const native = subturn.nativeThinkingChars ?? 0;
  const irat = subturn.iratThinkingChars ?? 0;
  const thinking = native + irat;
  const todoTotal = todoItems?.length ?? 0;
  const todoClosed =
    todoItems?.filter((item) => item.status === "closed").length ?? 0;

  if (toolCalls === 0 && thinking === 0 && todoTotal === 0) return null;
  return (
    <div css={rowCss}>
      {toolCalls > 0 && (
        <span css={pillCss}>
          <FaWrench size={9} />
          {plural(toolCalls, "tool call")}
        </span>
      )}
      {thinking > 0 && (
        <span
          css={pillCss}
          title={`Native: ${withCommas(native)} · IRAT: ${withCommas(irat)}`}
        >
          <FaBrain size={9} />
          {plural(thinking, "thinking char")}
        </span>
      )}
      {todoTotal > 0 && (
        <span css={pillCss} title="Top-level todo items fully closed">
          <FaListUl size={9} />
          {todoClosed}/{todoTotal} todos closed
        </span>
      )}
    </div>
  );
}
