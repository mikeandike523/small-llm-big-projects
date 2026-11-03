// Session-header email indicator + settings button (next to the heartbeat
// ones in Chat.tsx), plus the settings dialog it opens.
import { useState } from "react";
import { FaEnvelope } from "react-icons/fa";
import type { EmailSettings } from "../types";
import EmailSettingsDialog from "./EmailSettingsDialog";

interface Props {
  sessionId: string;
  settings: EmailSettings;
}

export default function EmailHeaderControls({ sessionId, settings }: Props) {
  const [open, setOpen] = useState(false);
  const active = settings.enabled && settings.alias !== "";
  const summary = active
    ? `Email: answering ${settings.alias}`
    : settings.alias
      ? `Email: disabled (alias ${settings.alias} reserved)`
      : "Email: disabled";
  return (
    <>
      {active && (
        <span
          title={summary}
          aria-label="Email enabled"
          style={{ display: "flex", color: "#7fb2e6" }}
        >
          <FaEnvelope size={14} />
        </span>
      )}
      <button
        onClick={() => setOpen(true)}
        title={summary}
        aria-label="Email settings"
        style={{
          background: "#101722",
          border: "1px solid #2a3a6e",
          borderRadius: 4,
          color: active ? "#8aacff" : "#666",
          fontFamily: "inherit",
          fontSize: 11,
          padding: "3px 6px",
          cursor: "pointer",
        }}
      >
        ✉
      </button>
      {open && (
        <EmailSettingsDialog
          sessionId={sessionId}
          settings={settings}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}
