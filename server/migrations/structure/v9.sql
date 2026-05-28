-- v9: Migrate old unprefixed "default" profile data to a real named profile.
--
-- Old installs stored the active profile's data under bare KV keys:
--   active_token, model, params.*
-- New installs (and going forward) use profiles.<name>.* for all profiles.
--
-- This migration finds an available name (unnamed, unnamed2, unnamed3, ...)
-- copies the bare keys to profiles.<name>.*, creates the profiles row,
-- sets active_profile to that name, and removes the old bare keys.
--
-- Fresh installs have no bare keys -> nothing is migrated -> the system
-- starts in "no profile selected" state, which is the intended initial state.
--
-- After migration, if active_profile is still the JSON string "default"
-- (i.e. nothing was migrated but the key was explicitly set), it is deleted
-- so the system enters "no profile selected" state cleanly.

DELIMITER $$

CREATE PROCEDURE _slbp_v9_migrate_default_profile()
BEGIN
  DECLARE has_data BOOLEAN DEFAULT FALSE;
  DECLARE chosen_name VARCHAR(255) DEFAULT 'unnamed';
  DECLARE counter INT DEFAULT 2;
  DECLARE found_name BOOLEAN DEFAULT FALSE;

  SELECT COUNT(*) > 0 INTO has_data
  FROM kv_store
  WHERE `key` IN ('active_token', 'model')
     OR `key` LIKE 'params.%';

  IF has_data THEN
    find_name: WHILE NOT found_name DO
      IF NOT EXISTS (SELECT 1 FROM profiles WHERE name = chosen_name) THEN
        SET found_name = TRUE;
      ELSE
        SET chosen_name = CONCAT('unnamed', counter);
        SET counter = counter + 1;
      END IF;
    END WHILE find_name;

    INSERT INTO profiles (name) VALUES (chosen_name);

    INSERT INTO kv_store (`key`, `value`)
    SELECT CONCAT('profiles.', chosen_name, '.', `key`), `value`
    FROM kv_store
    WHERE `key` IN ('active_token', 'model') OR `key` LIKE 'params.%';

    INSERT INTO kv_store (`key`, `value`)
    VALUES ('active_profile', JSON_QUOTE(chosen_name))
    ON DUPLICATE KEY UPDATE `value` = JSON_QUOTE(chosen_name);

    DELETE FROM kv_store
    WHERE `key` IN ('active_token', 'model') OR `key` LIKE 'params.%';
  END IF;

  DELETE FROM kv_store
  WHERE `key` = 'active_profile' AND `value` = '"default"';

END $$

DELIMITER ;

CALL _slbp_v9_migrate_default_profile();
DROP PROCEDURE IF EXISTS _slbp_v9_migrate_default_profile;
