import { css } from "@emotion/react";

const noticeCss = css`
  background: #111827;
  border: 1px dashed #5a4a2a;
  border-radius: 16px 16px 16px 4px;
  padding: 10px 16px;
  color: #b89a5a;
  font-style: italic;
  font-size: 13px;
`;

/** Shown for a subturn that ended without an answer (e.g. the server stopped
 *  mid-turn). The stored history is left as it was; the backend flags it. */
export default function InterruptedNotice() {
  return (
    <div css={noticeCss}>
      Interrupted — this request ended before an answer was given.
    </div>
  );
}
