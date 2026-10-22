#!/bin/bash

set -euo pipefail

local branch_name="$1"

cd "../slbp-worktrees/$branch_name" && exec "$SHELL"