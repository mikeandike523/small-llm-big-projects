#!/bin/bash
# Run a single tool call in the correct project environment.
#
# Usage:
#   ./run_tool.sh <tool_name> [json_args]
#
# Examples:
#   ./run_tool.sh get_pwd '{}'
#   ./run_tool.sh list_dir '{"path": "."}'
#   ./run_tool.sh basic_web_request '{"url": "https://example.com", "method": "GET", "content_type": "text/plain", "accept": "text/plain"}'
#
# Environment:
#   - Activates .venv and sets PYTHONPATH (via python_in_env.sh)
#   - Loads .env for credentials (API keys, Redis host, etc.)
#   - Uses Redis-backed session memory if Redis is reachable, else plain dict

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$REPO_ROOT/python_in_env.sh" "$REPO_ROOT/run_tool.py" "$@"
