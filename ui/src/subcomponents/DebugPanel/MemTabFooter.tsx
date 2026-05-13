import { memEventEmptyCss, memEventLabelCss } from "../../css/DebugPanel";
import { MemKeyEvent } from "../../types/DebugPanel";

export default function MemTabFooter({ event }: { event: MemKeyEvent | null }) {
  if (!event) {
    return <span css={memEventEmptyCss}>no events</span>;
  }
  const label = event.type === "deleted" ? "deleted" : "set";
  return (
    <span css={memEventLabelCss(event.type)} title={`${label}: "${event.key}"`}>
      {label}: &quot;{event.key}&quot;
    </span>
  );
}