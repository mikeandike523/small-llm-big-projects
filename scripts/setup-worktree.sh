#!/bin/bash

set -euo pipefail


# We only really use worktrees on windows for now
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt

cd ui
pnpm install
cd ..

cd desktop
pnpm install
cd ..

echo "Worktree setup complete."