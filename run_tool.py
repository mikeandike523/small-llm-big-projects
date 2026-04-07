"""
Standalone tool runner. Executes a single tool call and prints the result.

Usage:
    python run_tool.py <tool_name> [json_args]

json_args defaults to '{}' if omitted.

Environment is loaded from .env at the repo root (credentials, service tokens, etc.)
Session memory uses Redis if available, falls back to a plain dict.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Load .env before importing anything that touches DB / Redis / credentials
# ---------------------------------------------------------------------------
_repo_root = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv
    load_dotenv(_repo_root / ".env")
except ImportError:
    pass  # python-dotenv not installed; rely on shell environment

# ---------------------------------------------------------------------------
# Session data
# ---------------------------------------------------------------------------

def _make_session_data() -> dict:
    """Build a minimal session_data dict that mirrors the real agentic loop."""
    cwd = str(_repo_root)

    # Try Redis-backed memory (same as tool_tests) so stateful tools work fully.
    try:
        import uuid
        import redis
        from src.utils.redis_dict import RedisDict

        r = redis.Redis(
            host=os.environ.get("REDIS_HOST", "localhost"),
            port=int(os.environ.get("REDIS_PORT", 6379)),
            decode_responses=True,
        )
        r.ping()  # fail fast if Redis is not running
        hash_key = f"run_tool:session:{uuid.uuid4().hex[:8]}"
        memory = RedisDict(r, hash_key)
        _cleanup_redis = lambda: r.delete(hash_key)  # noqa: E731
    except Exception:
        memory = {}
        _cleanup_redis = lambda: None  # noqa: E731

    return {
        "memory": memory,
        "initial_cwd": cwd,
        "__pinned_project__": cwd,
        "_cleanup": _cleanup_redis,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: run_tool.py <tool_name> [json_args]", file=sys.stderr)
        sys.exit(1)

    tool_name = sys.argv[1]
    raw_args = sys.argv[2] if len(sys.argv) > 2 else "{}"

    try:
        args = json.loads(raw_args)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON args: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(args, dict):
        print("Error: args must be a JSON object", file=sys.stderr)
        sys.exit(1)

    from src.tools import execute_tool

    session_data = _make_session_data()
    cleanup = session_data.pop("_cleanup")

    try:
        result = execute_tool(tool_name, args, session_data)
        sys.stdout.buffer.write((result + "\n").encode("utf-8", errors="replace"))
    finally:
        cleanup()


if __name__ == "__main__":
    main()
