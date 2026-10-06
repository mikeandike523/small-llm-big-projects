"""
Update the demo server by SSHing in and running a deploy command.

Configuration lives in demo-server-config.jsonc at the repo root:

    {
      "user": "deploy",
      "hostname": "demo.example.com",
      "command": "cd /path && git pull && docker compose up -d --build"
    }

SSH identity (key) is resolved from ~/.ssh/config for the given hostname,
exactly the same way ``ssh demo.example.com`` does it — nothing secret
needs to live in the config file.
"""

from pathlib import Path
import sys

import json5
from fabric import Connection
from paramiko.config import SSHConfig

REPO_ROOT = Path(__file__).parent.parent.resolve()

# ---------------------------------------------------------------------------
# 1. Load user-facing config
# ---------------------------------------------------------------------------
CONFIG_PATH = REPO_ROOT / "demo-server-config.jsonc"
if not CONFIG_PATH.exists():
    sys.exit(
        f"Config file not found: {CONFIG_PATH}\n"
        "Create one with at least 'user', 'hostname', and 'command' keys."
    )

CONFIG = json5.loads(CONFIG_PATH.read_text())

REQUIRED = ("user", "hostname", "command")
for key in REQUIRED:
    if key not in CONFIG:
        sys.exit(f"Missing required config key: '{key}'")

# ---------------------------------------------------------------------------
# 2. Resolve SSH identity from ~/.ssh/config
# ---------------------------------------------------------------------------
SSH_CONFIG_PATH = Path.home() / ".ssh" / "config"
if not SSH_CONFIG_PATH.exists():
    sys.exit(f"SSH config not found: {SSH_CONFIG_PATH}")

ssh_cfg = SSHConfig()
ssh_cfg.parse(SSH_CONFIG_PATH.read_text())
host_entry = ssh_cfg.lookup(CONFIG["hostname"])

if not host_entry.get("hostname"):
    sys.exit(f"Host '{CONFIG['hostname']}' not found in {SSH_CONFIG_PATH}")

# ---------------------------------------------------------------------------
# 3. Connect and run the command
# ---------------------------------------------------------------------------
conn = Connection(
    host=host_entry["hostname"],
    user=CONFIG["user"],
    port=int(host_entry.get("port", 22)),
    connect_kwargs={
        "key_filename": host_entry.get("identityfile", []),
    },
)

print(f"Connecting to {CONFIG['user']}@{host_entry['hostname']} ...")
conn.run(CONFIG["command"], echo=True)
print("Done.")