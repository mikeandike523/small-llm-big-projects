-- v17: per-subturn thinking character counts.
--
-- Thinking text (native reasoning and IRAT "interim response as thinking") is
-- never persisted, so its size is recorded here as basic display metadata:
-- one row per subturn, counting streamed thinking characters. The agent loop
-- adds to the counts every 10 streamed chunks and once at the end of each LLM
-- exchange, so they can briefly lag the live stream. Deleting a session
-- removes its rows.
CREATE TABLE IF NOT EXISTS subturn_thinking_chars (
  session_id     VARCHAR(255) NOT NULL,
  subturn_id     VARCHAR(64) NOT NULL,
  native_chars   BIGINT UNSIGNED NOT NULL DEFAULT 0,
  irat_chars     BIGINT UNSIGNED NOT NULL DEFAULT 0,
  updated_at     TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
                 ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (session_id, subturn_id),
  CONSTRAINT fk_subturn_thinking_chars_session
    FOREIGN KEY (session_id) REFERENCES session_meta(session_id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
