-- v23: per-session email channel (alias claims + inbound queue).
--
-- session_meta.email_alias is the routing key for inbound mail. It is stored
-- normalized (ASCII-lowercased, validated in src/utils/email_addresses.py),
-- in an ASCII binary column, and is UNIQUE so at most one session can claim
-- an alias. NULL = no claim (many NULLs are allowed). Disabling email keeps
-- the claim; deleting the session (row) releases it.
ALTER TABLE session_meta
  ADD COLUMN email_enabled TINYINT(1) NOT NULL DEFAULT 0,
  ADD COLUMN email_alias VARCHAR(320) CHARACTER SET ascii COLLATE ascii_bin DEFAULT NULL,
  ADD COLUMN email_alias_claimed_at DOUBLE DEFAULT NULL,
  ADD UNIQUE KEY uq_session_meta_email_alias (email_alias);

-- One row per (session, Gmail message): the session's email work queue, its
-- de-duplication record (recovery and lease takeover may re-deliver mail),
-- and the "topic" every reply is threaded against (its RFC 5322 headers).
CREATE TABLE email_inbound (
  id                     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  session_id             VARCHAR(255) NOT NULL,
  gmail_message_id       VARCHAR(255) NOT NULL,
  gmail_thread_id        VARCHAR(255) NOT NULL,
  alias                  VARCHAR(320) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  sender_address         VARCHAR(320) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  subject                TEXT NOT NULL,
  message_id_header      TEXT NOT NULL,
  references_header      TEXT NOT NULL,
  body_text              MEDIUMTEXT NOT NULL,
  received_at            DOUBLE NOT NULL,
  status                 VARCHAR(16) NOT NULL DEFAULT 'queued',
  needs_queued_reply     TINYINT(1) NOT NULL DEFAULT 0,
  queued_reply_sent_at   DOUBLE DEFAULT NULL,
  working_reply_sent_at  DOUBLE DEFAULT NULL,
  final_reply_sent_at    DOUBLE DEFAULT NULL,
  final_text             MEDIUMTEXT DEFAULT NULL,
  error_detail           TEXT DEFAULT NULL,
  created_at             TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at             TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
                           ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  UNIQUE KEY uq_email_inbound_session_message (session_id, gmail_message_id),
  KEY idx_email_inbound_queue (session_id, status, received_at),
  KEY idx_email_inbound_status (status),
  CONSTRAINT fk_email_inbound_session
    FOREIGN KEY (session_id) REFERENCES session_meta(session_id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
