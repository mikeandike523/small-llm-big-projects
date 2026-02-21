from __future__ import annotations


def ensure_session_memory(session_data: dict) -> dict:
    """Return the session memory dict, creating it if absent."""
    memory = session_data.get("memory")
    if not isinstance(memory, dict):
        memory = {}
        session_data["memory"] = memory
    return memory
