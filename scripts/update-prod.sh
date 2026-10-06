#!/bin/bash

set -euo pipefail

bash python_in_env.sh -m pip install -r requirements.txt

cd ui

pnpm install

pnpm run build

cd ..

cd server

# bash migration-runner.sh up

# bash setup_piston.sh

cd ..

# Restart the server. Only Linux (including WSL) runs it as the slbp systemd
# service; on Windows (Git Bash/MSYS/Cygwin) and macOS the desktop app owns it.
case "$(uname -s)" in
  Linux)
    sudo systemctl restart slbp

    # wait 3 seconds with countdown
    for i in {3..1}; do
      echo "Waiting $i..."
      sleep 1
    done

    sudo systemctl status slbp --no-pager
    ;;
  MINGW* | MSYS* | CYGWIN* | Darwin)
    echo "Please restart server in desktop app."
    ;;
  *)
    echo "Unsupported OS '$(uname -s)': restart the server manually." >&2
    exit 1
    ;;
esac

