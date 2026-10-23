/** @jsxImportSource @emotion/react */
import { useEffect, useRef } from "react";
import { VscError, VscLoading } from "react-icons/vsc";
import { renameInputCss, rowStatusIconCss } from "../../css/FileExplorer";
import type { MutationStatus } from "./useEntryMutations";

export function EntryStatusIcon({ status }: { status: MutationStatus }) {
  if (status === "idle") return null;
  const failed = status === "failed";
  return (
    <span
      css={rowStatusIconCss(failed)}
      title={failed ? "Failed. Check Debug Panel logs." : "Working…"}
    >
      {failed ? <VscError size={13} /> : <VscLoading size={13} />}
    </span>
  );
}

interface Props {
  value: string;
  kind: "directory" | "file";
  status: MutationStatus;
  onChange: (value: string) => void;
  onCommit: () => void;
  onCancel: () => void;
}

/** Inline rename box: Enter commits, Escape cancels, blur commits a change. */
export default function EntryRenameInput({
  value,
  kind,
  status,
  onChange,
  onCommit,
  onCancel,
}: Props) {
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    // Wait a frame so the closing context menu doesn't take focus back.
    const animationFrame = window.requestAnimationFrame(() => {
      const input = inputRef.current;
      if (!input) return;
      input.focus();
      const dot = kind === "file" ? input.value.lastIndexOf(".") : -1;
      input.setSelectionRange(0, dot > 0 ? dot : input.value.length);
    });
    return () => window.cancelAnimationFrame(animationFrame);
    // Only select the name when the box first opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <>
      <input
        ref={inputRef}
        css={renameInputCss}
        value={value}
        readOnly={status === "pending"}
        spellCheck={false}
        aria-label="New name"
        onChange={(event) => onChange(event.target.value)}
        onClick={(event) => event.stopPropagation()}
        onKeyDown={(event) => {
          event.stopPropagation();
          if (event.key === "Enter") {
            event.preventDefault();
            onCommit();
          } else if (event.key === "Escape") {
            event.preventDefault();
            onCancel();
          }
        }}
        onBlur={() => {
          if (status === "pending") return;
          if (status === "failed") onCancel();
          else onCommit();
        }}
      />
      <EntryStatusIcon status={status} />
    </>
  );
}
