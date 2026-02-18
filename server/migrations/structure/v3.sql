CREATE TABLE IF NOT EXISTS projects (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  
  -- Store the canonical path as text (not indexed directly).
  path TEXT NOT NULL,

  -- A fixed-size hash of the canonical path, indexed and unique.
  -- Option A: compute in your app and insert as BINARY(32)
  path_hash BINARY(32) NOT NULL,

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  UNIQUE KEY uq_projects_path_hash (path_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;


CREATE TABLE IF NOT EXISTS project_memory (
  project_id BIGINT UNSIGNED NOT NULL,
  `key` VARCHAR(255) NOT NULL,
  `value` JSON NOT NULL,

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  -- Scoped by project:
  PRIMARY KEY (project_id, `key`),

  CONSTRAINT fk_project_memory_project
    FOREIGN KEY (project_id) REFERENCES projects(id)
    ON DELETE CASCADE
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;