import { css, keyframes } from "@emotion/react";
import PageNumberInput from "./PageNumberInput";

const barCss = css`
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 6px 16px;
  border-bottom: 1px solid #22304d;
  background: #0c121c;
  font-family: "Segoe UI", system-ui, sans-serif;
`;

const linksCss = css`
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
`;

const linkCss = css`
  min-width: 28px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 4px;
  color: #8aacff;
  font-size: 12px;
  font-family: inherit;
  padding: 3px 7px;
  cursor: pointer;
  &:hover:not(:disabled) {
    background: #16213a;
    border-color: #2a3a6e;
  }
  &:disabled {
    color: #3a4660;
    cursor: default;
  }
`;

const currentLinkCss = css`
  ${linkCss};
  background: #1d4ed8;
  border-color: #2d5fe8;
  color: #fff;
  cursor: default;
`;

const _unseenPulse = keyframes`
  0%, 100% { box-shadow: 0 0 0 0 rgba(224, 160, 48, 0.6); }
  50%      { box-shadow: 0 0 0 3px rgba(224, 160, 48, 0); }
`;

const unseenLinkCss = css`
  ${linkCss};
  color: #e0a030;
  border-color: #6a4a18;
  animation: ${_unseenPulse} 1.6s ease-in-out infinite;
`;

const gapCss = css`
  color: #5a6680;
  font-size: 12px;
  padding: 0 2px;
`;

/** Page numbers to show: first, last, and two either side of the current. */
function pageItems(page: number, total: number): (number | "gap")[] {
  const shown = new Set([1, total]);
  for (let n = page - 2; n <= page + 2; n++) {
    if (n >= 1 && n <= total) shown.add(n);
  }
  const items: (number | "gap")[] = [];
  let prev = 0;
  for (const n of [...shown].sort((a, b) => a - b)) {
    // A gap of exactly one page shows that page instead of an ellipsis.
    if (n - prev === 2) items.push(prev + 1);
    else if (n - prev > 2) items.push("gap");
    items.push(n);
    prev = n;
  }
  return items;
}

/** One turn per page: blog-style page links plus a page-number box. */
export default function TurnPagination({
  page,
  total,
  unseenLatest,
  onGo,
}: {
  page: number;
  total: number;
  /** The latest turn has news (new turn, follow-up, approval): highlight it. */
  unseenLatest: boolean;
  onGo: (page: number) => void;
}) {
  return (
    <nav css={barCss} aria-label="Turns">
      <div css={linksCss}>
        <button
          css={linkCss}
          disabled={page <= 1}
          onClick={() => onGo(page - 1)}
          aria-label="Previous turn"
        >
          ‹ Prev
        </button>
        {pageItems(page, total).map((item, i) =>
          item === "gap" ? (
            <span key={`gap-${i}`} css={gapCss}>
              …
            </span>
          ) : (
            <button
              key={item}
              css={
                item === page
                  ? currentLinkCss
                  : item === total && unseenLatest
                    ? unseenLinkCss
                    : linkCss
              }
              aria-current={item === page ? "page" : undefined}
              title={
                item === total && unseenLatest && item !== page
                  ? "The latest turn has new activity"
                  : undefined
              }
              onClick={() => item !== page && onGo(item)}
            >
              {item}
            </button>
          ),
        )}
        <button
          css={unseenLatest && page < total ? unseenLinkCss : linkCss}
          disabled={page >= total}
          onClick={() => onGo(page + 1)}
          aria-label="Next turn"
        >
          Next ›
        </button>
      </div>
      <PageNumberInput page={page} total={total} onGo={onGo} />
    </nav>
  );
}
