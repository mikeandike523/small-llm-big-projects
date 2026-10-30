-- v21: Gmail mailbox synchronization, durable push intake, and debug storage.
-- v20 has already shipped, so evolve it in place.

RENAME TABLE gmail_watch_state TO gmail_mailbox_state;

ALTER TABLE gmail_mailbox_state
  ADD COLUMN mailbox_email VARCHAR(320) DEFAULT NULL AFTER singleton_id,
  ADD COLUMN last_processed_history_id VARCHAR(255) DEFAULT NULL AFTER mailbox_email,
  ADD COLUMN initialization_started_unix DOUBLE DEFAULT NULL AFTER last_processed_history_id,
  ADD COLUMN watch_next_attempt_unix DOUBLE DEFAULT NULL AFTER last_success_unix,
  ADD COLUMN sync_last_attempt_unix DOUBLE DEFAULT NULL AFTER last_error,
  ADD COLUMN sync_last_success_unix DOUBLE DEFAULT NULL AFTER sync_last_attempt_unix,
  ADD COLUMN sync_last_error MEDIUMTEXT DEFAULT NULL AFTER sync_last_success_unix;

-- The v20 daemon never called Gmail or wrote renewal state; this was only an
-- empty seed row. Startup creates the configured mailbox row after validation.
DELETE FROM gmail_mailbox_state WHERE singleton_id = 1;

ALTER TABLE gmail_mailbox_state
  DROP CHECK chk_gmail_watch_state_singleton,
  DROP PRIMARY KEY,
  DROP COLUMN singleton_id,
  DROP COLUMN renewal_history_id,
  CHANGE COLUMN last_attempt_unix watch_last_attempt_unix DOUBLE DEFAULT NULL,
  CHANGE COLUMN last_success_unix watch_last_success_unix DOUBLE DEFAULT NULL,
  CHANGE COLUMN last_error watch_last_error MEDIUMTEXT DEFAULT NULL,
  MODIFY COLUMN mailbox_email VARCHAR(320) NOT NULL,
  ADD PRIMARY KEY (mailbox_email);

CREATE TABLE gmail_pubsub_notifications (
  pubsub_message_id      VARCHAR(255) NOT NULL,
  subscription_resource VARCHAR(512) NOT NULL,
  mailbox_email          VARCHAR(320) NOT NULL,
  notified_history_id    VARCHAR(255) NOT NULL,
  received_at            TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  processing_status      VARCHAR(32) NOT NULL DEFAULT 'pending',
  processing_attempts    INT UNSIGNED NOT NULL DEFAULT 0,
  processing_batch_id    VARCHAR(255) DEFAULT NULL,
  processed_at           TIMESTAMP(3) DEFAULT NULL,
  last_error             MEDIUMTEXT DEFAULT NULL,
  PRIMARY KEY (pubsub_message_id),
  KEY idx_gmail_notifications_pending (mailbox_email, processing_status, received_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE gmail_debug_messages (
  gmail_message_id       VARCHAR(255) NOT NULL,
  gmail_thread_id        VARCHAR(255) NOT NULL,
  gmail_history_id       VARCHAR(255) DEFAULT NULL,
  internal_date_ms       BIGINT UNSIGNED NOT NULL,
  direction              VARCHAR(16) NOT NULL,
  subject_text           TEXT NOT NULL,
  from_header            TEXT NOT NULL,
  to_header              TEXT NOT NULL,
  cc_header              TEXT NOT NULL,
  delivered_to_header    TEXT NOT NULL,
  original_to_header     TEXT NOT NULL,
  message_id_header      TEXT NOT NULL,
  in_reply_to_header     TEXT NOT NULL,
  references_header      TEXT NOT NULL,
  snippet                TEXT NOT NULL,
  text_body              LONGTEXT NOT NULL,
  html_body              LONGTEXT NOT NULL,
  labels_json            JSON NOT NULL,
  attachments_json       JSON NOT NULL,
  relevant_to_alias      TINYINT(1) NOT NULL DEFAULT 0,
  alias_match_reason     VARCHAR(255) DEFAULT NULL,
  observed_at            TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at             TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
                         ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (gmail_message_id),
  KEY idx_gmail_debug_thread (gmail_thread_id, internal_date_ms),
  KEY idx_gmail_debug_recent (internal_date_ms)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
