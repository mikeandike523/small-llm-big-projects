CREATE TABLE file_snapshots (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  session_id VARCHAR(255) NOT NULL,
  file_path TEXT NOT NULL,
  file_path_hash BINARY(32) NOT NULL,
  content LONGTEXT NOT NULL,
  snapshot_order INT UNSIGNED NOT NULL DEFAULT 0,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_session_file_order (session_id, file_path_hash, snapshot_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
