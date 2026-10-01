import { css } from "@emotion/react";

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

/** Full "Context Notes" (a subturn's detailed summary) in a modal overlay. */
export default function ContextNotesModal({
  text,
  onClose,
}: {
  text: string;
  onClose: () => void;
}) {
  return (
    <div css={compactionModalOverlayCss} onClick={() => onClose()}>
      <div css={compactionModalCss} onClick={(e) => e.stopPropagation()}>
        <div css={compactionModalTitleCss}>Context Notes</div>
        <div css={compactionModalBodyCss}>{text}</div>
        <button css={compactionModalCloseCss} onClick={() => onClose()}>
          Close
        </button>
      </div>
    </div>
  );
}
