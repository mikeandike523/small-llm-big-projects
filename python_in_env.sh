#!/bin/bash
# Activate the virtualenv and set PYTHONPATH to the repo root, then run
# the given Python script (or any command) with those settings in effect.
#
# Usage:
#   ./python_in_env.sh path/to/script.py [args...]
#   ./python_in_env.sh -m some.module [args...]

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Activate virtualenv (Windows path inside Git-Bash / MINGW64)
source "$REPO_ROOT/.venv/Scripts/activate"

# Prepend repo root to PYTHONPATH so that "from src.xxx" imports work
export PYTHONPATH="$REPO_ROOT:${PYTHONPATH:-}"

exec python "$@"
