-- v25: single-session email returns alongside agent pools, and queues drain by
-- sent date.
--
-- session_meta.email_alias is the routing key for mail answered by one session
-- (same columns as v23). An address has one owner, a session or an agent; the
-- server checks that across the two tables (src/utils/email_claims.py).
ALTER TABLE session_meta
  ADD COLUMN email_enabled TINYINT(1) NOT NULL DEFAULT 0,
  ADD COLUMN email_alias VARCHAR(320) CHARACTER SET ascii COLLATE ascii_bin DEFAULT NULL,
  ADD COLUMN email_alias_claimed_at DOUBLE DEFAULT NULL,
  ADD UNIQUE KEY uq_session_meta_email_alias (email_alias);

-- A queue row now belongs either to an agent's pool (agent_id set) or to one
-- session (agent_id NULL, session_id set). NULLs never clash in a unique key, so
-- each kind of row is de-duplicated by its own key.
--
-- Separate statements: MySQL may refuse adding and dropping a foreign key in the
-- same ALTER TABLE.
ALTER TABLE email_inbound
  DROP FOREIGN KEY fk_email_inbound_agent;

ALTER TABLE email_inbound
  MODIFY COLUMN agent_id VARCHAR(36) CHARACTER SET ascii COLLATE ascii_bin DEFAULT NULL,
  ADD COLUMN sent_at DOUBLE DEFAULT NULL AFTER received_at,
  ADD UNIQUE KEY uq_email_inbound_session_message (session_id, gmail_message_id);

ALTER TABLE email_inbound
  ADD CONSTRAINT fk_email_inbound_agent
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE;

-- Existing rows never recorded a sent date; Gmail's accepted time stands in.
UPDATE email_inbound SET sent_at = received_at;

ALTER TABLE email_inbound
  MODIFY COLUMN sent_at DOUBLE NOT NULL,
  DROP INDEX idx_email_inbound_queue,
  ADD KEY idx_email_inbound_queue (session_id, status, sent_at);
