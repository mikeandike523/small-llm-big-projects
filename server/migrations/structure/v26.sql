-- v26: agents are retired instead of unregistered.
--
-- A retired agent keeps its name, email, sessions and folder, so its pool card
-- can still show who it was and when it worked. It no longer holds its name or
-- email: another agent, or a single session, may claim them. Unretiring claims
-- them again and reactivates the same pool.
--
-- MySQL has no partial unique keys, so the claim is enforced on generated
-- columns that are NULL while the agent is retired (NULLs never clash).
ALTER TABLE agents
  ADD COLUMN retired_at DOUBLE DEFAULT NULL AFTER registered_at;

-- Agents unregistered under the old flow already lost their name and email.
-- They become retired agents with no identity left to reclaim.
UPDATE agents SET retired_at = created_at WHERE email IS NULL;

ALTER TABLE agents
  DROP INDEX uq_agents_name_key,
  DROP INDEX uq_agents_email;

ALTER TABLE agents
  ADD COLUMN active_name_key VARCHAR(320) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin
    GENERATED ALWAYS AS (IF(retired_at IS NULL, name_key, NULL)) STORED,
  ADD COLUMN active_email VARCHAR(320) CHARACTER SET ascii COLLATE ascii_bin
    GENERATED ALWAYS AS (IF(retired_at IS NULL, email, NULL)) STORED,
  ADD UNIQUE KEY uq_agents_active_name_key (active_name_key),
  ADD UNIQUE KEY uq_agents_active_email (active_email);
