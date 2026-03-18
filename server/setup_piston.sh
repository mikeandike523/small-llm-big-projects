#!/usr/bin/env bash
# setup_piston.sh
# One-time (or re-run after piston_packages.txt changes) setup script.
# Installs the Python runtime into Piston via its PPMAN API, then
# pip-installs every package listed in piston_packages.txt.
#
# Usage:
#   cd server
#   ./setup_piston.sh [PISTON_URL] [PYTHON_VERSION] [CONTAINER_NAME]
#
# Defaults:
#   PISTON_URL       auto-discovered via `docker compose port piston 2000`
#   PYTHON_VERSION   3.12.0
#   CONTAINER_NAME   server-piston-1   (docker compose default naming)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"

# ---------------------------------------------------------------------------
# Discover docker compose command (plugin mode first, then legacy standalone)
# ---------------------------------------------------------------------------
_find_docker_compose() {
    if docker compose version >/dev/null 2>&1; then
        echo "docker compose"
    elif docker-compose version >/dev/null 2>&1; then
        echo "docker-compose"
    else
        echo "ERROR: Neither 'docker compose' nor 'docker-compose' is available." >&2
        echo "       Install Docker Desktop or the standalone docker-compose binary." >&2
        exit 1
    fi
}

DC="$(_find_docker_compose)"

# ---------------------------------------------------------------------------
# Auto-discover PISTON_URL from docker compose port if not explicitly set
# ---------------------------------------------------------------------------
_discover_piston_url() {
    local port_output
    if port_output=$($DC -f "$COMPOSE_FILE" port piston 2000 2>/dev/null); then
        # Output is "0.0.0.0:PORT" or ":::PORT"
        local port="${port_output##*:}"
        echo "http://localhost:${port}"
    else
        echo ""
    fi
}

if [ -n "${1:-}" ]; then
    PISTON_URL="$1"
elif [ -n "${PISTON_URL:-}" ]; then
    : # already set in environment
else
    echo "==> Auto-discovering Piston host port via docker compose..."
    DISCOVERED="$(_discover_piston_url)"
    if [ -n "$DISCOVERED" ]; then
        PISTON_URL="$DISCOVERED"
        echo "    Discovered: $PISTON_URL"
    else
        PISTON_URL="http://localhost:2000"
        echo "    Could not discover port; falling back to $PISTON_URL"
    fi
fi

PYTHON_VERSION="${2:-${PISTON_PYTHON_VERSION:-3.12.0}}"
CONTAINER_NAME="${3:-${PISTON_CONTAINER:-server-piston-1}}"
PACKAGES_FILE="$(dirname "$0")/piston_packages.txt"

echo "==> Piston URL:       $PISTON_URL"
echo "==> Python version:   $PYTHON_VERSION"
echo "==> Container name:   $CONTAINER_NAME"
echo "==> Packages file:    $PACKAGES_FILE"
echo ""

# ---------------------------------------------------------------------------
# 1. Wait for Piston to be reachable
# ---------------------------------------------------------------------------
echo "==> Waiting for Piston to be ready..."
for i in $(seq 1 30); do
    if curl -sf "$PISTON_URL/api/v2/runtimes" > /dev/null 2>&1; then
        echo "    Piston is up."
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "ERROR: Piston did not become ready after 30 attempts. Is the container running?"
        exit 1
    fi
    echo "    Not ready yet (attempt $i/30), retrying in 2s..."
    sleep 2
done

# ---------------------------------------------------------------------------
# 2. Install the Python runtime via PPMAN
# ---------------------------------------------------------------------------
echo ""
echo "==> Installing Python $PYTHON_VERSION runtime via PPMAN..."
INSTALL_RESPONSE=$(curl -sf -X POST "$PISTON_URL/api/v2/packages" \
    -H "Content-Type: application/json" \
    -d "{\"language\": \"python\", \"version\": \"$PYTHON_VERSION\"}" \
    2>&1) || true

echo "    Response: $INSTALL_RESPONSE"

# Verify the runtime is now listed
echo "==> Verifying runtime is available..."
RUNTIMES=$(curl -sf "$PISTON_URL/api/v2/runtimes")
if echo "$RUNTIMES" | grep -q "\"python\""; then
    echo "    Python runtime confirmed."
else
    echo "WARNING: Python runtime not found in runtimes list. Output: $RUNTIMES"
    echo "         You may need to check the Piston container logs."
fi

# ---------------------------------------------------------------------------
# 3. Determine the Python binary path inside the container
# ---------------------------------------------------------------------------
# Piston installs runtimes to /piston/packages/<language>/<version>/
PYTHON_BIN="/piston/packages/python/$PYTHON_VERSION/bin/python3"

echo ""
echo "==> Python binary inside container: $PYTHON_BIN"

# ---------------------------------------------------------------------------
# 4. pip-install packages from piston_packages.txt
# ---------------------------------------------------------------------------
if [ ! -f "$PACKAGES_FILE" ]; then
    echo "WARNING: $PACKAGES_FILE not found. Skipping package installation."
    exit 0
fi

echo ""
echo "==> Installing packages from piston_packages.txt..."

while IFS= read -r line || [ -n "$line" ]; do
    # Strip leading/trailing whitespace
    pkg="$(echo "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    # Skip blank lines and comments
    [ -z "$pkg" ] && continue
    [[ "$pkg" == \#* ]] && continue

    echo "    pip install $pkg"
    # MSYS_NO_PATHCONV=1 prevents Git Bash from converting the Linux path
    # (e.g. /piston/packages/...) into a Windows path before passing it to docker.
    MSYS_NO_PATHCONV=1 docker exec "$CONTAINER_NAME" "$PYTHON_BIN" -m pip install -v "$pkg" \
        && echo "    OK: $pkg" \
        || echo "    FAILED: $pkg (check container logs)"
done < "$PACKAGES_FILE"

echo ""
echo "==> Done. Piston Python $PYTHON_VERSION is ready with packages from piston_packages.txt."
