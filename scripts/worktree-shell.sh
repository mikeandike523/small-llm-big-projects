#!/bin/bash

set -euo pipefail

branch_name="$1"

cd "../slbp-worktrees/$branch_name" && exec "$SHELL"