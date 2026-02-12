#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
	cat <<EOF
Usage: $(basename "$0") [options]

Runs SQL against a MySQL instance. Defaults are taken from env vars:
	MYSQL_HOST, MYSQL_PORT, MYSQL_DATABASE, MYSQL_USER, MYSQL_PASSWORD

Options:
	-h HOST      MySQL host (default: \$MYSQL_HOST or localhost)
	-p PORT      MySQL port (default: \$MYSQL_PORT or 3306)
	-d DATABASE  Database name (default: \$MYSQL_DATABASE)
	-u USER      Database user (default: \$MYSQL_USER)
	-P PASSWORD  Database password (default: \$MYSQL_PASSWORD)
	-f FILE      Run a single SQL file (absolute or relative path)
	-m DIR       Run all .sql files in DIR (no default; provide to run migrations)
	-n           Dry-run: print commands without executing
	--help       Show this help

Examples:
	$(basename "$0") -f ./migrations/initial.sql
	MYSQL_PASSWORD=secret $(basename "$0") -m ./migrations
EOF
}

# defaults
HOST="${MYSQL_HOST:-localhost}"
PORT="${MYSQL_PORT:-3306}"
DB="${MYSQL_DATABASE:-slbp}"
USER="${MYSQL_USER:-slbp}"
PASSWORD="${MYSQL_PASSWORD:-slbp}"
FILE=""
MIGRATIONS_DIR=""
DRY_RUN=0

while [[ $# -gt 0 ]]; do
	case "$1" in
		-h) HOST="$2"; shift 2;;
		-p) PORT="$2"; shift 2;;
		-d) DB="$2"; shift 2;;
		-u) USER="$2"; shift 2;;
		-P) PASSWORD="$2"; shift 2;;
		-f) FILE="$2"; shift 2;;
		-m) MIGRATIONS_DIR="$2"; shift 2;;
		-n) DRY_RUN=1; shift 1;;
		--help) usage; exit 0;;
		*) echo "Unknown arg: $1" >&2; usage; exit 2;;
	esac
done

if [[ -z "$DB" ]]; then
	echo "Error: database name not set. Provide with -d or set MYSQL_DATABASE." >&2
	exit 2
fi

# If we're targeting localhost and the port is default (or unset), try to autodiscover
# the host port mapped to the `mysql:3306` service using `docker compose`.
# This mirrors the detection used in src/data.py.
if [[ "$HOST" == "localhost" || "$HOST" == "127.0.0.1" ]]; then
	if [[ -z "${PORT:-}" || "$PORT" == "3306" ]]; then
		if command -v docker >/dev/null 2>&1; then
			if out=$(docker compose port mysql 3306 2>/dev/null); then
				# output is like "0.0.0.0:12345" or "::1:12345"
				port="${out##*:}"
				# strip newline
				port="${port%%$'\n'*}"
				if [[ -n "$port" ]]; then
					PORT="$port"
					HOST="localhost"
				fi
			fi
		fi
	fi
fi

run_mysql_file() {
	local sqlfile="$1"
	if [[ ! -f "$sqlfile" ]]; then
		echo "SQL file not found: $sqlfile" >&2
		return 1
	fi
	echo "-> Running: $sqlfile"
	if [[ $DRY_RUN -eq 1 ]]; then
		echo "DRY: mysql -h $HOST -P $PORT -u $USER -p*** -D $DB < $sqlfile"
		return 0
	fi
	mysql -h "$HOST" -P "$PORT" -u "$USER" -p"$PASSWORD" -D "$DB" < "$sqlfile"
}

if [[ -n "$FILE" ]]; then
	run_mysql_file "$FILE"
	exit $?
fi

if [[ -n "$MIGRATIONS_DIR" ]]; then
	if [[ -d "$MIGRATIONS_DIR" ]]; then
		shopt -s nullglob
		sqls=("$MIGRATIONS_DIR"/*.sql)
		if [[ ${#sqls[@]} -eq 0 ]]; then
			echo "No .sql files found in $MIGRATIONS_DIR" >&2
			exit 0
		fi
		for s in "${sqls[@]}"; do
			run_mysql_file "$s"
		done
		exit 0
	else
		echo "Migrations directory not found: $MIGRATIONS_DIR" >&2
		exit 2
	fi
fi

echo "Error: must provide -f FILE or -m DIR" >&2
usage
exit 2

