import { css } from "@emotion/react";
import { useEffect, useState } from "react";

const elapsedTimeCss = css`
  font-size: 11px;
  color: #7060a0;
  font-family: "Consolas", monospace;
  flex-shrink: 0;
  margin-left: 6px;
`;

export default function ElapsedTimer({
  startedAt,
  finishedAt,
}: {
  startedAt?: number;
  finishedAt?: number;
}) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!startedAt || finishedAt) return;
    const id = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(id);
  }, [startedAt, finishedAt]);

  if (!startedAt) return null;
  const elapsed = ((finishedAt ?? now) - startedAt) / 1000;
  return <span css={elapsedTimeCss}>{elapsed.toFixed(1)}s</span>;
}
