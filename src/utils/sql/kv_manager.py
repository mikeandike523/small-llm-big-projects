from __future__ import annotations

import hashlib
import json
import os
from typing import (
    Literal,
    Mapping,
    Optional,
    Protocol,
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


# ---------------------------------------------------------------------------
# Directory hashing utilities — kept for future knowledge-base scoping
# ---------------------------------------------------------------------------


def canonical_project_path(project: str) -> str:
    """Canonicalize a directory path for stable identity across platforms."""
    p = os.path.abspath(project)
    p = os.path.realpath(p)
    p = os.path.normpath(p)
    if os.name == "nt":
        p = os.path.normcase(p)
    return p


def project_path_hash(project: str) -> tuple[str, bytes]:
    """Return (canonical_path, sha256_digest) for a directory path."""
    canon = canonical_project_path(project)
    h = hashlib.sha256(canon.encode("utf-8")).digest()  # 32 bytes
    return canon, h


# ---------------------------------------------------------------------------
# KVManager — global kv_store (system config, params, profiles)
# ---------------------------------------------------------------------------


class KVManager:
    """Thin, stateless wrapper over the global kv_store table.

    Stores JSON-typed values (system config: model, params, tokens).
    JSON encoding/decoding is applied automatically.

    Does NOT manage transactions; caller controls connection lifetime.

    Schema assumption:
      kv_store(
        `key` VARCHAR(255) PRIMARY KEY,
        `value` JSON NOT NULL
      )
    """

    def __init__(self, conn: ConnLike) -> None:
        self._conn = conn

    @staticmethod
    def _normalize_json(value: object) -> JSONValue:
        if isinstance(value, str):
            return json.loads(value)
        return value  # type: ignore[return-value]

    def get_value(self, key: str, default=None):
        with self._conn.cursor(dictionary=True) as cur:
            cur.execute(
                "SELECT `value` FROM kv_store WHERE `key`=%s",
                (key,),
            )
            row: Optional[Mapping[str, object]] = cur.fetchone()

        if not row:
            return default

        return self._normalize_json(row["value"])

    def set_value(self, key: str, value) -> None:
        payload = json.dumps(value, ensure_ascii=False)
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

    def delete_value(self, key: str) -> None:
        with self._conn.cursor(dictionary=False) as cur:
            cur.execute(
                "DELETE FROM kv_store WHERE `key`=%s",
                (key,),
            )

    def exists(self, key: str) -> bool:
        with self._conn.cursor(dictionary=False) as cur:
            cur.execute(
                "SELECT 1 FROM kv_store WHERE `key`=%s LIMIT 1",
                (key,),
            )
            return cur.fetchone() is not None

    def list_keys(
        self,
        *,
        prefix: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> list[str]:
        """List keys in the global kv_store.

        Args:
            prefix: optional prefix filter (uses LIKE 'prefix%').
            limit: optional max number of keys.
            offset: pagination offset.

        Returns:
            List of keys ordered lexicographically.
        """
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
            limit_clause = " LIMIT 18446744073709551615 OFFSET %s"
            params.append(offset)

        sql = (
            "SELECT `key` FROM kv_store WHERE 1=1"
            + like_clause
            + " ORDER BY `key`"
            + limit_clause
        )
        with self._conn.cursor(dictionary=False) as cur:
            cur.execute(sql, tuple(params))
            return [str(r[0]) for r in cur.fetchall()]
