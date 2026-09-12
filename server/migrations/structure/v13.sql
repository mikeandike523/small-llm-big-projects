-- v13: persist last-known context usage per session so the ContextUsageBar
-- restores on session load (same semantics as total_cost_usd).
ALTER TABLE session_meta
  ADD COLUMN last_context_usage JSON NULL;
