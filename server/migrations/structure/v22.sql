-- v22: record automatic Gmail history-cursor recovery (expired startHistoryId).

ALTER TABLE gmail_mailbox_state
  ADD COLUMN cursor_reset_last_unix DOUBLE DEFAULT NULL AFTER sync_last_error,
  ADD COLUMN cursor_reset_last_detail MEDIUMTEXT DEFAULT NULL AFTER cursor_reset_last_unix;
