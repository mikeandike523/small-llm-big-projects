import { css } from "@emotion/react";

interface ContextUsageData {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number | null;
  known_max_context: number;
}

interface Props {
  data: ContextUsageData;
}

export default function ContextUsageBar({ data }: Props) {
  const { prompt_tokens, completion_tokens, total_tokens, known_max_context } =
    data;
  const currentTotal =
    total_tokens ?? prompt_tokens + completion_tokens;
  const percentage = (currentTotal / known_max_context) * 100;

  // Color based on percentage of context used
  let barColor: string;
  if (percentage > 95) {
    barColor = "#ff4444"; // red
  } else if (percentage > 80) {
    barColor = "#ff9800"; // orange
  } else if (percentage > 50) {
    barColor = "#ffc107"; // yellow
  } else {
    barColor = "#4caf50"; // green
  }

  const barCss = css`
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 4px 8px;
    background: #1a2332;
    border: 1px solid #2a3a6e;
    border-radius: 4px;
    font-size: 11px;
    color: #a0b8f0;
  `;

  const progressBarCss = css`
    width: 60px;
    height: 6px;
    background: #0a0f18;
    border-radius: 3px;
    overflow: hidden;
    border: 1px solid #2a3a6e;
  `;

  const fillCss = css`
    width: ${Math.min(percentage, 100)}%;
    height: 100%;
    background: ${barColor};
    transition: width 0.2s ease, background-color 0.2s ease;
  `;

  const textCss = css`
    white-space: nowrap;
    min-width: 120px;
  `;

  return (
    <div
      css={barCss}
      title={`Context usage: ${currentTotal.toLocaleString()}/${known_max_context.toLocaleString()} tokens`}
    >
      <div css={progressBarCss}>
        <div css={fillCss} />
      </div>
      <span css={textCss}>
        {Math.round(percentage)}% ({currentTotal.toLocaleString()}/
        {known_max_context.toLocaleString()})
      </span>
    </div>
  );
}