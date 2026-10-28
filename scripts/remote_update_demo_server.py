"""
Update the demo server by SSHing in and running a deploy command.

Configuration lives in demo-server-config.jsonc at the repo root:

    {
      "user": "deploy",
      "hostname": {
        "default": "demo.example.com",
        "on_dns_error": "demo-alt.local"
      },
      "command": "cd /path && git pull && docker compose up -d --build"
    }

Each hostname is an ~/.ssh/config Host alias, not necessarily a public DNS
name: the real HostName, port and identity (key) are resolved from
~/.ssh/config exactly the same way ``ssh demo.example.com`` does it — nothing
secret needs to live in the config file. If the default alias's HostName
fails DNS resolution, the ``on_dns_error`` alias is tried instead (e.g. one
whose HostName is an mDNS ``.local`` address). The old shape,
``"hostname": "<alias>"``, is still accepted.
"""

from pathlib import Path
import socket
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
ssh_cfg.parse(SSH_CONFIG_PATH.open("r"))


def host_aliases(hostname_cfg):
    """Ordered ssh-config aliases to try: default first, then the DNS fallback.

    Accepts the old shape (``"hostname": "<alias>"``) or the new one
    (``"hostname": {"default": "<alias>", "on_dns_error": "<alias>"}``).
    """
    if isinstance(hostname_cfg, str):
        return [hostname_cfg]
    if not isinstance(hostname_cfg, dict) or "default" not in hostname_cfg:
        sys.exit("'hostname' must be a string or an object with a 'default' key")
    aliases = [hostname_cfg["default"]]
    if hostname_cfg.get("on_dns_error"):
        aliases.append(hostname_cfg["on_dns_error"])
    return aliases


def connection_for(alias):
    host_entry = ssh_cfg.lookup(alias)
    if not host_entry.get("hostname"):
        sys.exit(f"Host '{alias}' not found in {SSH_CONFIG_PATH}")
    return Connection(
        host=host_entry["hostname"],
        user=CONFIG["user"],
        port=int(host_entry.get("port", 22)),
        connect_kwargs={
            "key_filename": host_entry.get("identityfile", []),
        },
    )


# ---------------------------------------------------------------------------
# 3. Connect (falling back to the alternate alias on DNS failure) and run
# ---------------------------------------------------------------------------
aliases = host_aliases(CONFIG["hostname"])
conn = None
for i, alias in enumerate(aliases):
    candidate = connection_for(alias)
    print(f"Connecting to {CONFIG['user']}@{candidate.host} (ssh alias '{alias}') ...")
    try:
        candidate.open()
    except socket.gaierror as e:
        if i == len(aliases) - 1:
            sys.exit(f"DNS lookup failed for '{candidate.host}': {e}")
        print(f"DNS lookup failed for '{candidate.host}' ({e}); trying fallback ...")
        continue
    conn = candidate
    break

# Remote output is UTF-8; invoke otherwise decodes with the Windows locale codepage.
for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding="utf-8", errors="replace")
conn.run(CONFIG["command"], echo=True, encoding="utf-8")
print("Done.")
