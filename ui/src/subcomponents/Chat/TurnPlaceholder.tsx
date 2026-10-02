import { css } from "@emotion/react";
import _spin from "../../css/_spin";

const boxCss = css`
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  height: 100%;
  font-family: "Segoe UI", system-ui, sans-serif;
  font-size: 13px;
  color: #8a94a6;
  text-align: center;
`;

const rowCss = css`
  display: flex;
  align-items: center;
  gap: 10px;
`;

const spinnerCss = css`
  width: 16px;
  height: 16px;
  border: 2px solid rgba(138, 172, 255, 0.2);
  border-top-color: #8aacff;
  border-radius: 50%;
  animation: ${_spin} 0.8s linear infinite;
`;

const errorCss = css`
  color: #e07070;
  max-width: 560px;
  word-break: break-word;
`;

const retryButtonCss = css`
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

/** Fills the turn area while a turn loads, failed to load, or none exist. */
export default function TurnPlaceholder({
  state,
  message,
  onRetry,
}: {
  state: "loading" | "error" | "empty";
  message?: string;
  onRetry?: () => void;
}) {
  if (state === "loading") {
    return (
      <div css={boxCss}>
        <div css={rowCss}>
          <div css={spinnerCss} />
          <span>{message ?? "Loading…"}</span>
        </div>
      </div>
    );
  }
  if (state === "error") {
    return (
      <div css={boxCss}>
        <span css={errorCss}>{message}</span>
        {onRetry && (
          <button css={retryButtonCss} onClick={onRetry}>
            Retry
          </button>
        )}
      </div>
    );
  }
  return (
    <div css={boxCss}>
      <span>{message ?? "No messages yet. Send one to start."}</span>
    </div>
  );
}
