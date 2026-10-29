-- v20: durable Gmail watch-renewal scheduler state.
--
-- This singleton row tracks watch registration/renewal only. The eventual
-- last-successfully-processed Gmail history checkpoint is intentionally kept
-- separate so renewing a watch can never skip unprocessed mail.
CREATE TABLE IF NOT EXISTS gmail_watch_state (
  singleton_id          TINYINT UNSIGNED NOT NULL,
  last_attempt_unix     DOUBLE DEFAULT NULL,
  last_success_unix     DOUBLE DEFAULT NULL,
  watch_expiration_ms   BIGINT UNSIGNED DEFAULT NULL,
  renewal_history_id    VARCHAR(255) DEFAULT NULL,
  lease_owner           VARCHAR(255) DEFAULT NULL,
  lease_expires_unix    DOUBLE DEFAULT NULL,
  last_error            TEXT,
  updated_at            TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
                        ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (singleton_id),
  CONSTRAINT chk_gmail_watch_state_singleton CHECK (singleton_id = 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO gmail_watch_state (singleton_id) VALUES (1);
