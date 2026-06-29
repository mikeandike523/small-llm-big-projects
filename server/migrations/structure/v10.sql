-- v10: Persistent sessions.
--
-- Until now sessions lived only in Redis (TTL 3600s, wiped on server boot).
-- This table makes MySQL the durable source of truth; Redis becomes a hot
-- write-through cache that is flushed on boot and rehydrated from here.
--
--   data         full session_to_dict() blob (turns, subturns, exchanges,
--                tool calls, config) -- everything EXCEPT the live RedisDict
--                memory hash, which session_to_dict intentionally excludes.
--   memory_json  snapshot of the session:{id}:memory hash (session_memory tool).
--   current_cwd  / total_cost_usd  -- state that lived only in Python memory
--                (state.py: _session_current_cwd / _session_costs).
--
-- Broken-out metadata columns exist so the dashboard list query stays cheap
-- without parsing every blob.

CREATE TABLE IF NOT EXISTS sessions (
  session_id      VARCHAR(255) NOT NULL,
  created_at      TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at      TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  schema_version  INT NOT NULL DEFAULT 0,
  profile_name    VARCHAR(255) DEFAULT NULL,
  initial_cwd     TEXT,
  current_cwd     TEXT,
  total_cost_usd  DOUBLE NOT NULL DEFAULT 0,
  data            JSON NOT NULL,
  memory_json     JSON NOT NULL,
  PRIMARY KEY (session_id),
  KEY idx_sessions_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
