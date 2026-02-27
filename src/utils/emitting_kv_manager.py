from __future__ import annotations

from src.utils.sql.kv_manager import KVManager


class EmittingKVManager:
    """
    A KVManager wrapper that emits SocketIO events after project_memory mutations.

    Constructed once per agentic turn (inside _execute_tools) using the pool,
    socketio instance, and the client's socket session ID (sid), then passed to
    tools via special_resources["emitting_kv_manager"].

    This keeps all emit logic out of the tool files and out of the socket handler's
    post-execution hooks.  Tools that accept special_resources and call
    emitting_kv.set_value / emitting_kv.delete_value automatically push UI updates
    without any extra wiring.

    Only project-scoped operations (project != None) emit events.
    Global kv_store operations (project=None) are silently delegated without emitting,
    since the UI panel only shows project memory.

    Each method opens its own short-lived connection from the pool so that this
    object can be constructed cheaply (no connection held open between calls).
    """

    def __init__(self, pool, socketio, sid: str) -> None:
        self._pool = pool
        self._socketio = socketio
        self._sid = sid

    # ------------------------------------------------------------------
    # Internal emit helper
    # ------------------------------------------------------------------

    def _emit(self, event: str, data: dict) -> None:
        if self._socketio:
            self._socketio.emit(event, data, room=self._sid)

    # ------------------------------------------------------------------
    # Mutating operations  (emit after success)
    # ------------------------------------------------------------------

    def set_value(self, key: str, value: str, *, project: str | None = None) -> None:
        """Write a project memory key and emit keys_update + key_event to the client."""
        with self._pool.get_connection() as conn:
            kv = KVManager(conn)
            kv.set_value(key, value, project=project)
            conn.commit()
            # List keys after commit within the same connection; InnoDB read-your-own-writes
            # guarantees the new key is visible here.
            keys = kv.list_keys(project=project) if project else None
        if project:
            self._emit("project_memory_keys_update", {"keys": keys})
            self._emit("project_memory_key_event", {"key": key, "type": "modified"})

    def delete_value(self, key: str, *, project: str | None = None) -> bool:
        """
        Delete a project memory key and emit keys_update + key_event.
        Returns True if the key existed before deletion, False otherwise.
        """
        with self._pool.get_connection() as conn:
            kv = KVManager(conn)
            existed = kv.exists(key, project=project)
            kv.delete_value(key, project=project)
            conn.commit()
            keys = kv.list_keys(project=project) if project else None
        if project:
            self._emit("project_memory_keys_update", {"keys": keys})
            self._emit("project_memory_key_event", {"key": key, "type": "deleted"})
        return existed

    # ------------------------------------------------------------------
    # Read-only operations  (no emit needed)
    # ------------------------------------------------------------------

    def get_value(self, key: str, default=None, *, project: str | None = None):
        with self._pool.get_connection() as conn:
            return KVManager(conn).get_value(key, default=default, project=project)

    def list_keys(
        self,
        *,
        project: str | None = None,
        prefix: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[str]:
        with self._pool.get_connection() as conn:
            return KVManager(conn).list_keys(
                project=project, prefix=prefix, limit=limit, offset=offset
            )

    def exists(self, key: str, *, project: str | None = None) -> bool:
        with self._pool.get_connection() as conn:
            return KVManager(conn).exists(key, project=project)
