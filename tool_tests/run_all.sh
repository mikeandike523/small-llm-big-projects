#!/bin/bash
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$REPO_ROOT/python_in_env.sh" "$REPO_ROOT/tool_tests/run.py" "$@"
