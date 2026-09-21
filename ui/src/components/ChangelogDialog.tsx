/** @jsxImportSource @emotion/react */
import { css } from "@emotion/react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  cmpSemver,
  fetchReleaseIndex,
  fetchReleaseNote,
  type ReleaseIndexEntry,
  type ReleaseSide,
} from "../api/releaseNotes";

// "View all changelogs" dialog. Opened via <dialog>.showModal(); dismissible
// with the ✕ button, Esc, or a backdrop click. The index is fetched first and
// all version sections render immediately with "…" placeholders; each note's
// message then loads asynchronously and independently.

const backdropCss = css`
  &::backdrop {
    background: rgba(2, 6, 14, 0.85);
  }
  border: none;
  border-radius: 8px;
  background: #101828;
  color: #dbe5ff;
  padding: 0;
  max-width: 480px;
  width: 90vw;
  max-height: 75vh;
  box-shadow: 0 8px 40px rgba(0, 0, 0, 0.5);
  position: fixed;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  margin: 0;
`;

const headerCss = css`
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid #26324a;
  font-size: 12px;
  font-weight: 600;
`;

const closeCss = css`
  background: none;
  border: none;
  color: #8a9ab8;
  font-size: 14px;
  cursor: pointer;
  padding: 2px 6px;
  &:hover {
    color: #dbe5ff;
  }
`;

const bodyCss = css`
  overflow-y: auto;
  padding: 10px 14px;
  font-size: 11px;
  line-height: 1.45;
  max-height: calc(75vh - 40px);
`;

const entryCss = css`
  margin-bottom: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid #1c2740;
  &:last-child {
    border-bottom: none;
  }
`;

const entryHeadCss = css`
  display: flex;
  gap: 8px;
  align-items: baseline;
  font-weight: 600;
`;

const dateCss = css`
  color: #6c7f9e;
  font-weight: 400;
  font-size: 10px;
`;

const messageCss = css`
  margin-top: 3px;
  color: #aebad2;
  white-space: pre-line;
`;

const emptyCss = css`
  color: #6c7f9e;
  font-style: italic;
`;

export default function ChangelogDialog({
  side,
  onClose,
}: {
  side: ReleaseSide;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [entries, setEntries] = useState<ReleaseIndexEntry[] | null>(null);
  // version -> message (or "" once loaded and empty / missing)
  const [messages, setMessages] = useState<Record<string, string>>({});

  useEffect(() => {
    const el = dialogRef.current;
    if (el && !el.open) el.showModal();
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchReleaseIndex(side).then((list) => {
      if (cancelled) return;
      // Sort latest-first so the dialog shows newest release at the top.
      const sorted = [...list].sort((a, b) => cmpSemver(b.version, a.version));
      setEntries(sorted);
      // Kick off independent async loads — each fills in its own slot.
      for (const e of list) {
        fetchReleaseNote(side, e.version).then((msg) => {
          if (cancelled) return;
          setMessages((prev) => ({ ...prev, [e.version]: msg?.trim() ?? "" }));
        });
      }
    });
    return () => {
      cancelled = true;
    };
  }, [side]);

  const handleBackdrop = useCallback((e: React.MouseEvent) => {
    // Clicks on the dialog element itself (outside the card's children) mean
    // the backdrop was clicked.
    if (e.target === dialogRef.current) onClose();
  }, [onClose]);

  return (
    <dialog ref={dialogRef} css={backdropCss} onClick={handleBackdrop} onClose={onClose}>
      <div css={headerCss}>
        <span>{side === "ui" ? "UI" : "Backend"} changelogs</span>
        <button css={closeCss} onClick={onClose} aria-label="Close">
          ✕
        </button>
      </div>
      <div css={bodyCss}>
        {entries === null ? (
          <div css={emptyCss}>Loading…</div>
        ) : entries.length === 0 ? (
          <div css={emptyCss}>No releases recorded yet</div>
        ) : (
          entries.map((e) => (
            <div key={e.version} css={entryCss}>
              <div css={entryHeadCss}>
                <span>v{e.version}</span>
                {e.date && <span css={dateCss}>{e.date}</span>}
              </div>
              <div css={messageCss}>
                {e.version in messages ? messages[e.version] || "—" : "…"}
              </div>
            </div>
          ))
        )}
      </div>
    </dialog>
  );
}
