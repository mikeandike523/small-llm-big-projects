-- v19: session memory as keyed rows.
--
-- Session memory used to live in a Redis hash, copied into the
-- `session_meta.memory_json` blob on save, so Redis briefly held the only copy
-- of every change. It is now read and written directly in MySQL, one row per
-- key: a set or delete touches one row, and any process (e.g. a tool running
-- in its own subprocess) sees the same data. Redis no longer holds memory.
--
-- mem_key is case-sensitive (utf8mb4_bin) like the old Redis hash fields.
-- 500 characters keeps the primary key within InnoDB's 3072-byte limit.

CREATE TABLE IF NOT EXISTS session_memory (
  session_id  VARCHAR(255) NOT NULL,
  mem_key     VARCHAR(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  value       LONGTEXT NOT NULL,
  PRIMARY KEY (session_id, mem_key),
  CONSTRAINT fk_session_memory_session
    FOREIGN KEY (session_id) REFERENCES session_meta(session_id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Copy each memory_json member into its own row. The member name is quoted
-- into the JSON path with `\` and `"` escaped.
INSERT IGNORE INTO session_memory (session_id, mem_key, value)
SELECT
  m.session_id,
  k.mem_key,
  JSON_UNQUOTE(JSON_EXTRACT(
    m.memory_json,
    CONCAT('$."', REPLACE(REPLACE(k.mem_key, '\\', '\\\\'), '"', '\\"'), '"')
  ))
FROM session_meta m
JOIN JSON_TABLE(
  JSON_KEYS(m.memory_json),
  '$[*]' COLUMNS (mem_key VARCHAR(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin PATH '$')
) k
WHERE m.memory_json IS NOT NULL AND JSON_TYPE(m.memory_json) = 'OBJECT';

ALTER TABLE session_meta
  DROP COLUMN memory_json;
