-- v14: dashboard/session-page heartbeat indicator.
--
-- Denormalizes the `enabled` flag from session_data.heartbeat_settings into
-- session_meta so the dashboard list query (which never touches session_data)
-- can show a heartbeat indicator per session without loading full session state.
ALTER TABLE session_meta
  ADD COLUMN heartbeat_enabled TINYINT(1) NOT NULL DEFAULT 0;
