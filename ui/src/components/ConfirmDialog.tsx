/** @jsxImportSource @emotion/react */
import { useEffect } from "react";
import type { ReactNode } from "react";
import {
  modalActionsCss,
  modalBodyCss,
  modalBoxCss,
  modalCancelBtnCss,
  modalDeleteBtnCss,
  modalOverlayCss,
  modalTitleCss,
} from "../css/ConfirmDialog";

interface Props {
  title: string;
  children: ReactNode;
  confirmLabel: string;
  busyLabel?: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/** Destructive-action confirmation modal (red title, Cancel / confirm). */
export default function ConfirmDialog({
  title,
  children,
  confirmLabel,
  busyLabel,
  busy = false,
  onConfirm,
  onCancel,
}: Props) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onCancel();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [busy, onCancel]);

  return (
    <div css={modalOverlayCss} onClick={() => !busy && onCancel()}>
      <div
        css={modalBoxCss}
        role="alertdialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <div css={modalTitleCss}>{title}</div>
        <div css={modalBodyCss}>{children}</div>
        <div css={modalActionsCss}>
          <button
            css={modalCancelBtnCss}
            onClick={onCancel}
            disabled={busy}
            autoFocus
          >
            Cancel
          </button>
          <button css={modalDeleteBtnCss} onClick={onConfirm} disabled={busy}>
            {busy && busyLabel ? busyLabel : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
