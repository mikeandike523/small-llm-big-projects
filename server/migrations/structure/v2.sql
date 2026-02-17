--  Establish a super-simple key-value store for json
--  great for super basic config variables

CREATE TABLE IF NOT EXISTS kv_store (
  `key` VARCHAR(255) PRIMARY KEY,
  `value` JSON NOT NULL
);