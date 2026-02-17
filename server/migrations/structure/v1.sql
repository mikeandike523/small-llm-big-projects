-- Tokens

CREATE TABLE known_providers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    provider_key VARCHAR(255) NOT NULL UNIQUE,
    display_name VARCHAR(255) NOT NULL,
    default_endpoint_url VARCHAR(255)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE tokens (
    id INT AUTO_INCREMENT PRIMARY KEY,
    provider VARCHAR(255) NOT NULL,
    endpoint_url VARCHAR(255),
    token_name VARCHAR(255) NOT NULL DEFAULT '',
    token_value TEXT NOT NULL,
    UNIQUE KEY tokens_provider_token_name_uniq (provider, token_name)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
