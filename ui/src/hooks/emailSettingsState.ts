// Email settings state for one session, kept outside useSocketWiring so that
// file only needs a few hook-up lines. Mirrors the heartbeat settings wiring:
// `session_state` sets the value and revision outright; a later
// `session_settings_update` applies only when its revision is not older.
import { useCallback, useRef, useState } from "react";
import type { EmailSettings } from "../types";
import { DEFAULT_EMAIL_SETTINGS } from "../types";

export interface EmailSettingsWire {
  emailSettings?: EmailSettings;
  emailSettingsRevision?: number;
}

export function useEmailSettingsState() {
  const revisionRef = useRef(0);
  const [emailSettings, setEmailSettings] = useState<EmailSettings>(
    DEFAULT_EMAIL_SETTINGS,
  );

  const applySessionState = useCallback((data: EmailSettingsWire) => {
    if (data.emailSettings !== undefined) {
      setEmailSettings({ ...DEFAULT_EMAIL_SETTINGS, ...data.emailSettings });
    }
    revisionRef.current = data.emailSettingsRevision ?? 0;
  }, []);

  const applySettingsUpdate = useCallback((data: EmailSettingsWire) => {
    if (
      data.emailSettings !== undefined &&
      (data.emailSettingsRevision ?? 0) >= revisionRef.current
    ) {
      revisionRef.current = data.emailSettingsRevision ?? 0;
      setEmailSettings({ ...DEFAULT_EMAIL_SETTINGS, ...data.emailSettings });
    }
  }, []);

  return {
    emailSettings,
    setEmailSettings,
    applySessionState,
    applySettingsUpdate,
  };
}
