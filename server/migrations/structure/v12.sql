-- v12: Slack session mappings for DM-based Slack integration.
--
-- Maps a Slack workspace user to a backend session_id so that a DM conversation
-- continues on the same session until the user sends "/new" (which generates a
-- fresh session_id).
--
-- One row per (slack_team_id, slack_user_id), meaning each user gets exactly
-- one active session per workspace.

CREATE TABLE IF NOT EXISTS slack_session_mappings (
  slack_team_id    VARCHAR(32) NOT NULL,
  slack_user_id    VARCHAR(32) NOT NULL,
  session_id       VARCHAR(255) NOT NULL,
  created_at       TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at       TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
                   ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (slack_team_id, slack_user_id),
  KEY idx_slack_session (session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;