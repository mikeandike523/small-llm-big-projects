import { css } from "@emotion/react";

export const modalOverlayCss = css`
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
`;

export const modalBoxCss = css`
  background: #181818;
  border: 1px solid #3a1a1a;
  border-radius: 10px;
  padding: 28px 32px;
  max-width: 420px;
  width: 90%;
  display: flex;
  flex-direction: column;
  gap: 18px;
  font-family: "Fira Code", "Consolas", monospace;
`;

export const modalTitleCss = css`
  font-size: 15px;
  font-weight: 700;
  color: #cc4444;
  letter-spacing: 1px;
`;

export const modalBodyCss = css`
  font-size: 12px;
  color: #eef3ff;
  line-height: 1.6;
`;

export const modalActionsCss = css`
  display: flex;
  justify-content: flex-end;
  gap: 10px;
`;

export const modalCancelBtnCss = css`
  background: none;
  border: 1px solid #30405f;
  border-radius: 5px;
  color: #eef3ff;
  padding: 7px 18px;
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  &:hover {
    border-color: #8aa4d8;
    color: #fff;
  }
`;

export const modalDeleteBtnCss = css`
  background: #2a0a0a;
  border: 1px solid #cc2222;
  border-radius: 5px;
  color: #ee4444;
  padding: 7px 18px;
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  font-weight: 600;
  &:hover {
    background: #3a0a0a;
    border-color: #ff4444;
  }
  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
`;
