from __future__ import annotations

import hashlib
import json
import os
from typing import (
    Literal,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    TypeAlias,
    overload,
)

from mysql.connector.cursor import MySQLCursor, MySQLCursorDict


# ---- JSON typing ----
JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


# ---- Minimal structural typing for connection ----
class ConnLike(Protocol):
    @overload
    def cursor(self, *, dictionary: Literal[True]) -> MySQLCursorDict: ...

    @overload
    def cursor(self, *, dictionary: Literal[False] = False) -> MySQLCursor: ...


class KVManager:
    """Thin, mostly-stateless wrapper over kv_store (global) and project_memory (scoped).

    If project is None: operate on global kv_store.
    If project is not None: resolve/ensure a project row and operate on project_memory.

    - Does NOT manage transactions.
    - Does NOT commit or rollback.
    - Caller controls connection lifetime + transaction scope.

    Schema assumptions:

      projects(
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        path TEXT NOT NULL,
        path_hash BINARY(32) NOT NULL UNIQUE
      )

      project_memory(
        project_id BIGINT NOT NULL,
        `key` VARCHAR(255) NOT NULL,
        `value` JSON NOT NULL,
        PRIMARY KEY (project_id, `key`),
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
      )

      kv_store(
        `key` VARCHAR(255) PRIMARY KEY,
        `value` JSON NOT NULL
      )
    """

    def __init__(self, conn: ConnLike,default_project=None):
        self._conn = conn
        # Cache project_id by path_hash (bytes) for speed within this manager instance.
        self._project_id_cache: dict[bytes, int] = {}
        self._default_project=default_project

    # ---------------------------
    # Internal helpers
    # ---------------------------

    @staticmethod
    def _normalize_json(value: object) -> JSONValue:
        # mysql-connector may return JSON as str or already-decoded python objects
        if isinstance(value, str):
            return json.loads(value)
        return value  # type: ignore[return-value]

    @staticmethod
    def _canonical_project_path(project: str) -> str:
        """Canonicalize a project path for stable identity.

        Uses abspath + realpath + normpath, and on Windows also normalizes case.
        """

        p = os.path.abspath(project)
        p = os.path.realpath(p)
        p = os.path.normpath(p)
        if os.name == "nt":
            p = os.path.normcase(p)
        return p

    @classmethod
    def _project_hash(cls, project: str) -> tuple[str, bytes]:
        canon = cls._canonical_project_path(project)
        h = hashlib.sha256(canon.encode("utf-8")).digest()  # 32 bytes for BINARY(32)
        return canon, h

    def _get_or_create_project_id(self, project: str) -> int:
        canon, h = self._project_hash(project)

        cached = self._project_id_cache.get(h)
        if cached is not None:
            return cached

        # Single-round-trip upsert that returns existing id via LAST_INSERT_ID.
        with self._conn.cursor(dictionary=False) as cur:
            cur.execute(
                """
                INSERT INTO projects (path, path_hash)
                VALUES (%s, %s)
                AS incoming
                ON DUPLICATE KEY UPDATE
                  id = LAST_INSERT_ID(id),
                  path = incoming.path
                """,
                (canon, h),
            )
            cur.execute("SELECT LAST_INSERT_ID()")
            row = cur.fetchone()

        if not row:
            raise RuntimeError("Failed to resolve project id")

        project_id = int(row[0])
        self._project_id_cache[h] = project_id
        return project_id

    # ---------------------------
    # Public API
    # ---------------------------

    def get_value(
        self,
        key: str,
        default: Optional[JSONValue] = None,
        *,
        project: Optional[str] = None,
    ) -> Optional[JSONValue]:

        if project is None and self._default_project:
            project = self._default_project
        if project is None:
            with self._conn.cursor(dictionary=True) as cur:
                cur.execute(
                    "SELECT `value` FROM kv_store WHERE `key`=%s",
                    (key,),
                )
                row: Optional[Mapping[str, object]] = cur.fetchone()

            if not row:
                return default

            return self._normalize_json(row["value"])

        project_id = self._get_or_create_project_id(project)
        with self._conn.cursor(dictionary=True) as cur:
            cur.execute(
                "SELECT `value` FROM project_memory WHERE project_id=%s AND `key`=%s",
                (project_id, key),
            )
            row: Optional[Mapping[str, object]] = cur.fetchone()

        if not row:
            return default
        return self._normalize_json(row["value"])

    def set_value(
        self,
        key: str,
        value: JSONValue,
        *,
        project: Optional[str] = None,
    ) -> None:
        if project is None and self._default_project:
            project = self._default_project
        payload = json.dumps(value, ensure_ascii=False)

        if project is None:
            with self._conn.cursor(dictionary=False) as cur:
                cur.execute(
                    """
                    INSERT INTO kv_store (`key`, `value`)
                    VALUES (%s, %s)
                    AS incoming
                    ON DUPLICATE KEY UPDATE `value` = incoming.`value`
                    """,
                    (key, payload),
                )
            return

        project_id = self._get_or_create_project_id(project)
        with self._conn.cursor(dictionary=False) as cur:
            cur.execute(
                """
                INSERT INTO project_memory (project_id, `key`, `value`)
                VALUES (%s, %s, %s)
                AS incoming
                    ON DUPLICATE KEY UPDATE `value` = incoming.`value`
                """,
                (project_id, key, payload),
            )

    def delete_value(self, key: str, *, project: Optional[str] = None) -> None:
        if project is None and self._default_project:
            project = self._default_project
        if project is None:
            with self._conn.cursor(dictionary=False) as cur:
                cur.execute(
                    "DELETE FROM kv_store WHERE `key`=%s",
                    (key,),
                )
            return

        project_id = self._get_or_create_project_id(project)
        with self._conn.cursor(dictionary=False) as cur:
            cur.execute(
                "DELETE FROM project_memory WHERE project_id=%s AND `key`=%s",
                (project_id, key),
            )

    def exists(self, key: str, *, project: Optional[str] = None) -> bool:
        if project is None and self._default_project:
            project = self._default_project
        if project is None:
            with self._conn.cursor(dictionary=False) as cur:
                cur.execute(
                    "SELECT 1 FROM kv_store WHERE `key`=%s LIMIT 1",
                    (key,),
                )
                return cur.fetchone() is not None

        project_id = self._get_or_create_project_id(project)
        with self._conn.cursor(dictionary=False) as cur:
            cur.execute(
                "SELECT 1 FROM project_memory WHERE project_id=%s AND `key`=%s LIMIT 1",
                (project_id, key),
            )
            return cur.fetchone() is not None

    def list_keys(
        self,
        *,
        project: Optional[str] = None,
        prefix: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> list[str]:
        """List keys in either global or project scope.

        Args:
            project: if None, list from kv_store; else list from project_memory for that project.
            prefix: optional prefix filter (uses LIKE 'prefix%').
            limit: optional max number of keys.
            offset: pagination offset.

        Returns:
            List of keys (strings) ordered lexicographically.
        """

        if project is None and self._default_project:
            project = self._default_project

        # Build query fragments safely
        like_clause = ""
        params: list[object] = []

        if prefix is not None:
            like_clause = " AND `key` LIKE %s"
            params.append(prefix + "%")

        limit_clause = ""
        if limit is not None:
            if limit < 0:
                raise ValueError("limit must be non-negative")
            if offset < 0:
                raise ValueError("offset must be non-negative")
            limit_clause = " LIMIT %s OFFSET %s"
            params.extend([limit, offset])
        elif offset:
            # MySQL requires LIMIT if OFFSET is provided
            limit_clause = " LIMIT 18446744073709551615 OFFSET %s"
            params.append(offset)

        if project is None:
            sql = (
                "SELECT `key` FROM kv_store WHERE 1=1"
                + like_clause
                + " ORDER BY `key`"
                + limit_clause
            )
            with self._conn.cursor(dictionary=False) as cur:
                cur.execute(sql, tuple(params))
                return [str(r[0]) for r in cur.fetchall()]

        project_id = self._get_or_create_project_id(project)
        sql = (
            "SELECT `key` FROM project_memory WHERE project_id=%s"
            + like_clause
            + " ORDER BY `key`"
            + limit_clause
        )
        with self._conn.cursor(dictionary=False) as cur:
            cur.execute(sql, tuple([project_id] + params))
            return [str(r[0]) for r in cur.fetchall()]
