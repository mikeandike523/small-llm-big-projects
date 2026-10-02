import { css } from "@emotion/react";
import { useEffect, useState } from "react";

const wrapCss = css`
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #8a94a6;
`;

const inputCss = (invalid: boolean) => css`
  background: #101722;
  color: #f3f6ff;
  border: 1px solid ${invalid ? "#a04848" : "#30405f"};
  border-radius: 4px;
  padding: 3px 6px;
  font-family: "Consolas", monospace;
  font-size: 12px;
  text-align: center;
  outline: none;
  box-sizing: content-box;
  &:focus {
    border-color: ${invalid ? "#d06060" : "#8aa4d8"};
  }
`;

const goButtonCss = css`
  background: #2563eb;
  color: #fff;
  border: none;
  border-radius: 4px;
  padding: 3px 9px;
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  &:hover {
    background: #3b74f0;
  }
`;

/**
 * "Turn [ n ] of N" page box. A plain text input (not type=number): only
 * digits can be typed, it widens with the digits, and the page changes on
 * Enter or the "Go" button, which shows only while the box differs from the
 * current page. An invalid or out-of-range value restores the current page.
 */
export default function PageNumberInput({
  page,
  total,
  onGo,
}: {
  page: number;
  total: number;
  onGo: (page: number) => void;
}) {
  const [draft, setDraft] = useState(String(page));
  useEffect(() => setDraft(String(page)), [page]);

  const parsed = draft === "" ? NaN : Number(draft);
  const valid = Number.isInteger(parsed) && parsed >= 1 && parsed <= total;
  const changed = draft !== String(page);

  function commit() {
    if (valid && parsed !== page) onGo(parsed);
    else setDraft(String(page));
  }

  return (
    <div css={wrapCss}>
      <span>Turn</span>
      <input
        type="text"
        inputMode="numeric"
        aria-label="Turn number"
        css={inputCss(changed && !valid)}
        style={{ width: `${Math.max(draft.length, 1)}ch` }}
        value={draft}
        onChange={(e) => setDraft(e.target.value.replace(/\D/g, ""))}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit();
          } else if (e.key === "Escape") {
            setDraft(String(page));
          }
        }}
      />
      <span>of {total}</span>
      {changed && (
        <button css={goButtonCss} onClick={commit}>
          Go
        </button>
      )}
    </div>
  );
}
