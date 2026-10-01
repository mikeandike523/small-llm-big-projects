import { css } from "@emotion/react";

const bannerCss = css`
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin: 0 16px 8px;
  padding: 8px 12px;
  background: #2a0d0d;
  border: 1px solid #5a1e1e;
  border-radius: 8px;
  color: #f0a0a0;
  font-family: "Segoe UI", system-ui, sans-serif;
  font-size: 13px;
  line-height: 1.4;
`;

const messageCss = css`
  flex: 1;
  white-space: pre-wrap;
  word-break: break-word;
`;

const dismissCss = css`
  background: none;
  border: none;
  color: #f0a0a0;
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  padding: 0 2px;
  &:hover {
    color: #fff;
  }
`;

/** A session-level error (one not tied to a turn), e.g. a failed database save. */
export default function SessionErrorBanner({
  message,
  onDismiss,
}: {
  message: string | null;
  onDismiss: () => void;
}) {
  if (!message) return null;
  return (
    <div css={bannerCss} role="alert">
      <span css={messageCss}>{message}</span>
      <button css={dismissCss} onClick={onDismiss} aria-label="Dismiss error">
        ×
      </button>
    </div>
  );
}
