#!/bin/bash

set -euo pipefail

bash python_in_env.sh -m pip install -r requirements.txt

cd ui

pnpm install

pnpm run build

cd ..

cd server

bash migration-runner.sh up

bash setup_piston.sh

cd ..

sudo systemctl restart slbp

# wait 3 seconds with countdown
for i in {3..1}; do
  echo "Waiting $i..."
  sleep 1
done

sudo systemctl status slbp --no-pager

