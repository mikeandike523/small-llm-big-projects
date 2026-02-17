# kv_manager.py

from __future__ import annotations

import json
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
    """
    Thin, stateless wrapper over kv_store table.

    - Does NOT manage transactions.
    - Does NOT commit or rollback.
    - Caller controls connection lifetime + transaction scope.
    """

    def __init__(self, conn: ConnLike):
        self._conn = conn

    # ---------------------------
    # Internal helpers
    # ---------------------------

    @staticmethod
    def _normalize_json(value: object) -> JSONValue:
        if isinstance(value, str):
            return json.loads(value)
        return value  # type: ignore[return-value]

    # ---------------------------
    # Public API
    # ---------------------------

    def get_value(
        self,
        key: str,
        default: Optional[JSONValue] = None,
    ) -> Optional[JSONValue]:
        with self._conn.cursor(dictionary=True) as cur:
            cur.execute(
                "SELECT `value` FROM kv_store WHERE `key`=%s",
                (key,),
            )
            row: Optional[Mapping[str, object]] = cur.fetchone()

        if not row:
            return default

        return self._normalize_json(row["value"])

    def set_value(self, key: str, value: JSONValue) -> None:
        payload = json.dumps(value)

        with self._conn.cursor(dictionary=True) as cur:
            cur.execute(
                """
                INSERT INTO kv_store (`key`, `value`)
                VALUES (%s, CAST(%s AS JSON))
                ON DUPLICATE KEY UPDATE `value` = VALUES(`value`)
                """,
                (key, payload),
            )

    def delete_value(self, key: str) -> None:
        with self._conn.cursor(dictionary=True) as cur:
            cur.execute(
                "DELETE FROM kv_store WHERE `key`=%s",
                (key,),
            )

    def exists(self, key: str) -> bool:
        with self._conn.cursor(dictionary=True) as cur:
            cur.execute(
                "SELECT 1 FROM kv_store WHERE `key`=%s LIMIT 1",
                (key,),
            )
            return cur.fetchone() is not None