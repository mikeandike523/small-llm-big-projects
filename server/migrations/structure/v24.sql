-- v24: agent session pools replace per-session email settings.
--
-- An agent owns a name + email pair, its allowlist and the settings its sessions
-- use. Each conversation (agent, Gmail thread, sender) gets its own session.
-- A NULL name/email means the agent is unregistered and holds no claim.
--
-- Existing email_inbound rows and session alias claims are prototype data and
-- are dropped here. The sessions themselves stay, as ordinary sessions.
CREATE TABLE agents (
  id                         VARCHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  slug                       VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  name                       VARCHAR(80) DEFAULT NULL,
  name_key                   VARCHAR(320) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  email                      VARCHAR(320) CHARACTER SET ascii COLLATE ascii_bin DEFAULT NULL,
  registered_at              DOUBLE DEFAULT NULL,
  enabled                    TINYINT(1) NOT NULL DEFAULT 1,
  allowed_senders            JSON NOT NULL,
  profile_name               VARCHAR(255) NOT NULL,
  approval_mode              VARCHAR(32) NOT NULL,
  automation_approval_policy VARCHAR(32) NOT NULL,
  created_at                 DOUBLE NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_agents_slug (slug),
  UNIQUE KEY uq_agents_name_key (name_key),
  UNIQUE KEY uq_agents_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- One row per person an agent has heard from. The slug names their folder and
-- never changes, even if the display name in their From header does.
CREATE TABLE agent_senders (
  agent_id       VARCHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  sender_address VARCHAR(320) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  slug           VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  display_name   VARCHAR(255) DEFAULT NULL,
  PRIMARY KEY (agent_id, sender_address),
  UNIQUE KEY uq_agent_senders_slug (agent_id, slug),
  CONSTRAINT fk_agent_senders_agent
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE session_meta
  DROP INDEX uq_session_meta_email_alias,
  DROP COLUMN email_enabled,
  DROP COLUMN email_alias,
  DROP COLUMN email_alias_claimed_at,
  ADD COLUMN agent_id VARCHAR(36) CHARACTER SET ascii COLLATE ascii_bin DEFAULT NULL,
  ADD KEY idx_session_meta_agent (agent_id);

ALTER TABLE session_meta
  ADD CONSTRAINT fk_session_meta_agent
    FOREIGN KEY (agent_id) REFERENCES agents(id);

-- The session answering one conversation. Deleting the session removes the row,
-- so a later reply in that thread starts a new session.
CREATE TABLE agent_conversations (
  agent_id        VARCHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  gmail_thread_id VARCHAR(255) NOT NULL,
  sender_address  VARCHAR(320) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  session_id      VARCHAR(255) NOT NULL,
  PRIMARY KEY (agent_id, gmail_thread_id, sender_address),
  UNIQUE KEY uq_agent_conversations_session (session_id),
  CONSTRAINT fk_agent_conversations_agent
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
  CONSTRAINT fk_agent_conversations_session
    FOREIGN KEY (session_id) REFERENCES session_meta(session_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Rows are keyed by agent, so the de-duplication record outlives a deleted
-- session and re-delivered mail cannot be answered twice.
DELETE FROM email_inbound;

-- Separate statements: MySQL may refuse adding and dropping a foreign key in the
-- same ALTER TABLE.
ALTER TABLE email_inbound
  DROP FOREIGN KEY fk_email_inbound_session;

ALTER TABLE email_inbound
  DROP INDEX uq_email_inbound_session_message,
  MODIFY COLUMN session_id VARCHAR(255) DEFAULT NULL,
  ADD COLUMN agent_id VARCHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL AFTER id,
  ADD COLUMN sender_display_name VARCHAR(255) DEFAULT NULL AFTER sender_address,
  ADD COLUMN approval_notice_requested_at DOUBLE DEFAULT NULL AFTER final_reply_sent_at,
  ADD COLUMN approval_notice_sent_at DOUBLE DEFAULT NULL AFTER approval_notice_requested_at,
  ADD UNIQUE KEY uq_email_inbound_agent_message (agent_id, gmail_message_id),
  ADD KEY idx_email_inbound_conversation (agent_id, gmail_thread_id, sender_address);

ALTER TABLE email_inbound
  ADD CONSTRAINT fk_email_inbound_session
    FOREIGN KEY (session_id) REFERENCES session_meta(session_id) ON DELETE SET NULL,
  ADD CONSTRAINT fk_email_inbound_agent
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE;
