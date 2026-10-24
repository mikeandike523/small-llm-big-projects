-- v18: keyed chat-history cache.
--
-- Every lookup into a session's history used to scan or unwrap JSON payloads in
-- `session_events`. These tables hold the small, frequently-read pieces as real
-- columns. `session_events` stays the source of truth and is unchanged; the
-- tables below are written in the same transaction as the events they describe.
--
--   chat_turn_index     one row per turn. turn_seq is the 1-based UI page
--                       number; start_event_id is the turn's `turn_started` event
--                       id, so turn N's events are the id range
--                       [start_N, start_N+1).
--   chat_history_cache  one row per subturn with exactly what later LLM requests
--                       need from a closed subturn: the user message, the final
--                       answer and the Context Notes summary.
--
-- `session_meta.history_cache_compatible` says the two tables are complete for
-- that session. Existing sessions start at 0 (the backend falls back to a full
-- replay) until `slbp intense-migration run fill-session-cache` fills them; new
-- sessions get 1 from the column default.

CREATE TABLE IF NOT EXISTS chat_turn_index (
  session_id      VARCHAR(255) NOT NULL,
  turn_seq        INT NOT NULL,
  turn_id         VARCHAR(64) NOT NULL,
  start_event_id  BIGINT NOT NULL,
  title           TEXT,
  completed       TINYINT(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (session_id, turn_seq),
  UNIQUE KEY uq_chat_turn_index_turn (session_id, turn_id),
  CONSTRAINT fk_chat_turn_index_session
    FOREIGN KEY (session_id) REFERENCES session_meta(session_id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS chat_history_cache (
  session_id              VARCHAR(255) NOT NULL,
  turn_seq                INT NOT NULL,
  subturn_seq             INT NOT NULL,
  subturn_id              VARCHAR(64) NOT NULL,
  user_text               MEDIUMTEXT,
  user_text_with_context  MEDIUMTEXT,
  final_response          MEDIUMTEXT,
  detailed_summary        MEDIUMTEXT,
  is_continuation         TINYINT(1) NOT NULL DEFAULT 0,
  approval_mode           VARCHAR(64) DEFAULT NULL,
  origin                  VARCHAR(32) NOT NULL DEFAULT 'user',
  PRIMARY KEY (session_id, turn_seq, subturn_seq),
  UNIQUE KEY uq_chat_history_cache_subturn (session_id, subturn_id),
  CONSTRAINT fk_chat_history_cache_session
    FOREIGN KEY (session_id) REFERENCES session_meta(session_id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Existing rows get 0; the default then flips so every new session gets 1.
ALTER TABLE session_meta
  ADD COLUMN history_cache_compatible TINYINT(1) NOT NULL DEFAULT 0;
ALTER TABLE session_meta
  ALTER COLUMN history_cache_compatible SET DEFAULT 1;

-- The dashboard shows the last few task titles and a count, so store just
-- that instead of every title (which was rewritten on every save).
ALTER TABLE session_meta
  ADD COLUMN recent_task_titles JSON DEFAULT NULL AFTER task_titles,
  ADD COLUMN task_title_count INT NOT NULL DEFAULT 0 AFTER recent_task_titles;

UPDATE session_meta
SET
  task_title_count = COALESCE(JSON_LENGTH(task_titles), 0),
  recent_task_titles = CASE
    WHEN task_titles IS NULL THEN JSON_ARRAY()
    WHEN JSON_LENGTH(task_titles) <= 4 THEN task_titles
    ELSE JSON_EXTRACT(task_titles, '$[last-3 to last]')
  END;

ALTER TABLE session_meta
  DROP COLUMN task_titles;
