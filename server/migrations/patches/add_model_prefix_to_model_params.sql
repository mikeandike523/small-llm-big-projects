-- Rename LLM generation params to use the params.model.* namespace.
-- This separates model-level params from system-level params (e.g. params.system.*).
-- Safe to run when keys do not exist — UPDATE simply affects 0 rows.

UPDATE kv_store SET `key` = 'params.model.temperature' WHERE `key` = 'params.temperature';
UPDATE kv_store SET `key` = 'params.model.top_p'       WHERE `key` = 'params.top_p';
UPDATE kv_store SET `key` = 'params.model.top_k'       WHERE `key` = 'params.top_k';
UPDATE kv_store SET `key` = 'params.model.max_tokens'  WHERE `key` = 'params.max_tokens';
