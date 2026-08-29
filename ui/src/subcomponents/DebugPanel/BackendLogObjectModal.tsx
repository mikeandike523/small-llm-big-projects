import {
  modalBodyCss,
  modalCardCss,
  modalCloseButtonCss,
  modalHeaderCss,
  modalOverlayCss,
  modalTitleCss,
} from "../../css/DebugPanel";
import JsonArgsViewer from "../../components/JsonArgsViewer";

// Single shared modal instance -- rendered once by BackendLogsTab, not per log
// entry. `entry` is null when closed.
export default function BackendLogObjectModal({
  entry,
  onClose,
}: {
  entry: { id: number; content: Record<string, unknown> | unknown[] } | null;
  onClose: () => void;
}) {
  if (entry === null) return null;

  return (
    <div css={modalOverlayCss} onClick={onClose}>
      <div css={modalCardCss} onClick={(e) => e.stopPropagation()}>
        <div css={modalHeaderCss}>
          <span css={modalTitleCss}>Log Entry #{entry.id}</span>
          <button css={modalCloseButtonCss} onClick={onClose}>
            ×
          </button>
        </div>
        <div css={modalBodyCss}>
          <JsonArgsViewer args={entry.content} />
        </div>
      </div>
    </div>
  );
}
