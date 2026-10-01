import { css } from "@emotion/react";
import _spin from "../../css/_spin";
import type { HistoryProgress } from "../../hooks/historyLoad";

const rowCss = css`
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 12px 0;
  font-family: "Segoe UI", system-ui, sans-serif;
  font-size: 13px;
  color: #8a94a6;
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
  ${rowCss};
  color: #e07070;
`;

/** Shown under the last loaded turn while the session history streams in. */
export default function HistoryLoadingRow({
  loading,
  progress,
  error,
}: {
  loading: boolean;
  progress: HistoryProgress;
  error: string | null;
}) {
  if (error) return <div css={errorCss}>{error}</div>;
  if (!loading) return null;
  return (
    <div css={rowCss}>
      <div css={spinnerCss} />
      <span>
        Loading history…
        {progress.total !== null && progress.total > 0
          ? ` ${progress.loaded} / ${progress.total}`
          : ""}
      </span>
    </div>
  );
}
