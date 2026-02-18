#!/bin/bash
# Activate the project virtualenv then launch the Flask/SocketIO UI connector.
# Intended to be called by `slbp ui run` via Git Bash.

set -euo pipefail

dn="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"

if [ -f "$dn/.venv/Scripts/activate" ]; then
    source "$dn/.venv/Scripts/activate"
elif [ -f "$dn/.venv/bin/activate" ]; then
    source "$dn/.venv/bin/activate"
else
    echo "No virtualenv activation script found in $dn/.venv" >&2
    exit 1
fi

export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}$dn"

python "$dn/src/ui_connector/main.py"
