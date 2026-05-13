import { useStickToBottom } from "use-stick-to-bottom";
import { BackendLogEntry } from "../../types/DebugPanel";
import { logLineCss, logsPanelCss, placeholderCss } from "../../css/DebugPanel";
import Ansi from "ansi-to-react";

export default function BackendLogsTab({
  logs,
  visible,
}: {
  logs: BackendLogEntry[];
  visible: boolean;
}) {
  const { scrollRef, contentRef } = useStickToBottom();

  return (
    <div ref={scrollRef} css={logsPanelCss(visible)}>
      <div ref={contentRef}>
        {logs.length === 0 ? (
          <div css={placeholderCss}>No logs yet.</div>
        ) : (
          logs.map((entry) => (
            <div key={entry.id} css={logLineCss}>
              <Ansi>{entry.text}</Ansi>
            </div>
          ))
        )}
      </div>
    </div>
  );
}