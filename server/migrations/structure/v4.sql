-- Tokens for known services
-- The endpoint is pre-programmed / known by tool
-- No need for configurable endpoint

CREATE TABLE service_tokens (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

  -- e.g. 'github', 'stripe', 'openai'
  provider VARCHAR(64) NOT NULL,

  -- token/secret value (may be long)
  value TEXT NOT NULL,

  -- optional label (default blank so uniqueness works consistently)
  name VARCHAR(128) NOT NULL DEFAULT '',

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (id),

  -- enforce one token per (provider, name) where name can be '' for the default token
  UNIQUE KEY uq_provider_name (provider, name),

  -- useful for lookups by provider
  KEY idx_provider (provider)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;