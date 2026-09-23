-- v15: merge custom skill/tool loading into one session setting.
-- Existing sessions remain enabled only when both legacy paths were present.
ALTER TABLE session_meta
  ADD COLUMN load_custom_skills_tools TINYINT(1) NOT NULL DEFAULT 0
  AFTER interim_response_as_thinking;

UPDATE session_meta
SET load_custom_skills_tools = (
  skills_path IS NOT NULL AND skills_path <> ''
  AND custom_tools_path IS NOT NULL AND custom_tools_path <> ''
);

ALTER TABLE session_meta
  DROP COLUMN skills_path,
  DROP COLUMN custom_tools_path;
