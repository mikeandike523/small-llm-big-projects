-- v11: Event-sourced sessions.
--
-- Replaces the v10 single-blob `sessions` table (which made the dashboard list
-- query filesort over multi-MB JSON blobs -> MySQL error 1038 "Out of sort
-- memory") with two tables:
--
--   session_meta    one slim row per session. Drives the dashboard list with a
--                   cheap, indexed `ORDER BY created_at` over small rows -- it
--                   never touches the event payloads. Also the durable home for
--                   per-session state that used to live only in Python memory
--                   (current_cwd, total_cost_usd) and the session_memory hash.
--
--   session_events  append-only log of semantic events (session_created,
--                   turn_started, title_set, subturn_started, exchange_recorded,
--                   turn_completed, ...). A session is reconstructed by selecting
--                   its events in `id` order and replaying them in memory.
--
-- BREAKING: the old `sessions` table (schema v5 blobs) is dropped; pre-v11
-- sessions are intentionally discarded.

DROP TABLE IF EXISTS sessions;

CREATE TABLE IF NOT EXISTS session_meta (
  session_id                   VARCHAR(255) NOT NULL,
  -- created_at is the authoritative session wall-clock as a unix epoch DOUBLE
  -- (matches Session.created_at and the float contract of the list API).
  created_at                   DOUBLE NOT NULL DEFAULT 0,
  updated_at                   TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  schema_version               INT NOT NULL DEFAULT 0,
  profile_name                 VARCHAR(255) DEFAULT NULL,
  initial_cwd                  TEXT,
  current_cwd                  TEXT,
  total_cost_usd               DOUBLE NOT NULL DEFAULT 0,
  turn_count                   INT NOT NULL DEFAULT 0,
  task_titles                  JSON,
  interim_response_as_thinking TINYINT(1) NOT NULL DEFAULT 0,
  skills_path                  TEXT,
  custom_tools_path            TEXT,
  corrupt                      TINYINT(1) NOT NULL DEFAULT 0,
  memory_json                  JSON,
  PRIMARY KEY (session_id),
  KEY idx_session_meta_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS session_events (
  id           BIGINT NOT NULL AUTO_INCREMENT,
  session_id   VARCHAR(255) NOT NULL,
  event_type   VARCHAR(64) NOT NULL,
  payload      JSON NOT NULL,
  created_at   TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_events_session (session_id, id),
  KEY idx_events_type (session_id, event_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
