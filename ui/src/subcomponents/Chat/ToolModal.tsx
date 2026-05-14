import { css } from "@emotion/react";
import { Dispatch, SetStateAction } from "react";
import scrollbarCss from "../../css/scrollBarCss";
import Ansi from "ansi-to-react";

const modalOverlayBaseCss = css`
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  transition: opacity 0.2s ease;
`;

const modalOverlayVisibleCss = css`
  opacity: 1;
  pointer-events: auto;
`;

const modalOverlayHiddenCss = css`
  opacity: 0;
  pointer-events: none;
`;

const modalCardCss = css`
  background: #181818;
  border: 1px solid #444;
  border-radius: 12px;
  box-shadow: 0 12px 48px rgba(0, 0, 0, 0.8);
  width: 80%;
  max-width: 900px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
`;

const modalHeaderCss = css`
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  border-bottom: 1px solid #333;
  background: #1e1e1e;
  flex-shrink: 0;
`;

const modalTitleCss = css`
  color: #7ec87e;
  font-family: "Consolas", monospace;
  font-size: 13px;
  font-style: normal;
`;

const modalCloseButtonCss = css`
  background: transparent;
  color: #888;
  border: none;
  font-size: 22px;
  cursor: pointer;
  padding: 0 4px;
  line-height: 1;
  &:hover {
    color: #ccc;
  }
`;

const modalBodyCss = css`
  ${scrollbarCss}
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
  font-family: "Consolas", monospace;
  font-size: 13px;
  color: #7ec87e;
  white-space: pre-wrap;
  word-break: break-word;
  background: #0a1a0a;
  line-height: 1.6;
  & code {
    display: block;
    font-family: inherit;
    background: transparent;
    padding: 0;
    margin: 0;
  }
`;

export default function ToolModal({
  modalContent,
  setModalContent,
}: {
  modalContent: string | null;
  setModalContent: Dispatch<SetStateAction<string | null>>;
}) {
  {
    /* Shared modal for full tool result */
  }
  return (
    <div
      css={[
        modalOverlayBaseCss,
        modalContent !== null ? modalOverlayVisibleCss : modalOverlayHiddenCss,
      ]}
      onClick={() => setModalContent(null)}
    >
      <div css={modalCardCss} onClick={(e) => e.stopPropagation()}>
        <div css={modalHeaderCss}>
          <span css={modalTitleCss}>Tool Result</span>
          <button
            css={modalCloseButtonCss}
            onClick={() => setModalContent(null)}
          >
            ×
          </button>
        </div>
        <div css={modalBodyCss}>
          <Ansi>{modalContent ?? ""}</Ansi>
        </div>
      </div>
    </div>
  );
}
