"""
Standalone tool runner. Executes a single tool call and prints the result.

Usage:
    python run_tool.py <tool_name> [--<key> <json_value> | --<key>=<json_value> | --<key>] ...

Each flag is assembled into the args object:
  --flag          -> {"flag": true}
  --flag=<json>   -> {"flag": <parsed json>}
  --flag <json>   -> {"flag": <parsed json>}

Example:
    python run_tool.py list_dir --path '"src"' --max_depth 2

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
    import argparse

    parser = argparse.ArgumentParser(
        prog="run_tool.py",
        description="Execute a single tool call and print the result.",
        add_help=True,
    )
    parser.add_argument("tool_name", help="Name of the tool to run")

    # Collect remaining flags as unknown args so keys are fully dynamic.
    parsed, unknown = parser.parse_known_args()
    tool_name = parsed.tool_name

    # Walk the unknown tokens and build the args dict.
    # Supports: --key=<json>, --key <json>, --key (bare flag → true)
    args: dict = {}
    tokens = unknown
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if not tok.startswith("--"):
            parser.error(f"unexpected argument {tok!r}")
        if "=" in tok:
            # --key=value form
            key, _, raw = tok[2:].partition("=")
            try:
                args[key] = json.loads(raw)
            except json.JSONDecodeError as e:
                parser.error(f"invalid JSON for --{key}: {e}")
        else:
            key = tok[2:]
            # Peek at next token: if it exists and doesn't start with '--', treat as value
            if i + 1 < len(tokens) and not tokens[i + 1].startswith("--"):
                raw = tokens[i + 1]
                i += 1
                try:
                    args[key] = json.loads(raw)
                except json.JSONDecodeError as e:
                    parser.error(f"invalid JSON for --{key}: {e}")
            else:
                # Bare flag → boolean true
                args[key] = True
        i += 1

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
