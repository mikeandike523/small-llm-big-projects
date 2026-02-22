-- Change project_memory.value from JSON to LONGTEXT so that
-- the value column is a plain text blob with no enforced structure.
-- The LLM now stores and retrieves raw text; if it needs structured
-- data it can write JSON/TOML/etc. as text without a double-encoding layer.

ALTER TABLE project_memory
  MODIFY COLUMN `value` LONGTEXT NOT NULL;
