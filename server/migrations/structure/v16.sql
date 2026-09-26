-- v16: durable heartbeat scheduler run history.
--
-- One row per session records the Unix timestamp of its most recent successful
-- heartbeat callback. Deleting a session removes its scheduler state too.
CREATE TABLE IF NOT EXISTS heartbeat_last_runs (
  session_id     VARCHAR(255) NOT NULL,
  last_run_unix  DOUBLE NOT NULL,
  updated_at     TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
                 ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (session_id),
  CONSTRAINT fk_heartbeat_last_runs_session
    FOREIGN KEY (session_id) REFERENCES session_meta(session_id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
