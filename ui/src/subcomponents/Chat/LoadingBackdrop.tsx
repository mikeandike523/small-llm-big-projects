import { css } from "@emotion/react";
import _spin from "../../css/_spin";

const loadingOverlayCss = css`
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
`;

const loadingCardCss = css`
  background: #ffffff;
  border-radius: 16px;
  padding: 36px 52px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 20px;
  box-shadow: 0 8px 40px rgba(0, 0, 0, 0.25);
`;

const loadingTextCss = css`
  font-family: "Segoe UI", system-ui, sans-serif;
  font-size: 15px;
  color: #444;
  font-weight: 500;
`;

const loadingSpinnerCss = css`
  width: 32px;
  height: 32px;
  border: 3px solid rgba(37, 99, 235, 0.2);
  border-top-color: #2563eb;
  border-radius: 50%;
  animation: ${_spin} 0.8s linear infinite;
`;

export default function LoadingBackdrop({
  isLoadingBackendState,
}: {
  isLoadingBackendState: boolean;
}) {
  return (
    isLoadingBackendState && (
      <div css={loadingOverlayCss}>
        <div css={loadingCardCss}>
          <div css={loadingSpinnerCss} />
          <span css={loadingTextCss}>loading backend state...</span>
        </div>
      </div>
    )
  );
}
