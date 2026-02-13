#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
	cat <<EOF
Usage: $(basename "$0") [options]

Runs SQL against the MySQL container via docker compose exec.
Defaults are taken from env vars: MYSQL_DATABASE, MYSQL_USER, MYSQL_PASSWORD

Options:
	-d DATABASE  Database name (default: \$MYSQL_DATABASE or slbp)
	-u USER      Database user (default: \$MYSQL_USER or slbp)
	-P PASSWORD  Database password (default: \$MYSQL_PASSWORD or slbp)
	-f FILE      Run a single SQL file (absolute or relative path)
	-c SQL       Run inline SQL (accepts multiple statements; quote as needed)
	-m DIR       Run all .sql files in DIR (no default; provide to run migrations)
	-n           Dry-run: print commands without executing
	--help       Show this help

Examples:
	$(basename "$0") -f ./migrations/initial.sql
	MYSQL_PASSWORD=secret $(basename "$0") -m ./migrations
EOF
}

# defaults
DB="${MYSQL_DATABASE:-slbp}"
USER="${MYSQL_USER:-slbp}"
PASSWORD="${MYSQL_PASSWORD:-slbp}"
FILE=""
SQL=""
MIGRATIONS_DIR=""
DRY_RUN=0
STDIN_PRESENT=0
STDIN_FILE=""

while [[ $# -gt 0 ]]; do
	case "$1" in
		-d) DB="$2"; shift 2;;
		-u) USER="$2"; shift 2;;
		-P) PASSWORD="$2"; shift 2;;
		-f) FILE="$2"; shift 2;;
		-c) SQL="$2"; shift 2;;
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

COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
MYSQL_ARGS=(mysql -u "$USER" -p"$PASSWORD" -D "$DB" --show-warnings --verbose)

cleanup() {
	if [[ -n "$STDIN_FILE" && -f "$STDIN_FILE" ]]; then
		rm -f "$STDIN_FILE"
	fi
}
trap cleanup EXIT

if [[ ! -t 0 ]]; then
	STDIN_PRESENT=1
	STDIN_FILE="$(mktemp)"
	cat > "$STDIN_FILE"
	if [[ ! -s "$STDIN_FILE" ]]; then
		STDIN_PRESENT=0
		rm -f "$STDIN_FILE"
		STDIN_FILE=""
	fi
fi

if [[ $STDIN_PRESENT -eq 1 ]]; then
	if [[ -n "$FILE" || -n "$SQL" || -n "$MIGRATIONS_DIR" ]]; then
		echo "Error: stdin provided; -f, -c, and -m are invalid when stdin is present." >&2
		exit 2
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
		echo "DRY: docker compose -f $COMPOSE_FILE exec -T mysql mysql -u $USER -p*** -D $DB --show-warnings --verbose < $sqlfile"
		return 0
	fi
	docker compose -f "$COMPOSE_FILE" exec -T mysql "${MYSQL_ARGS[@]}" < "$sqlfile"
}

run_mysql_sql() {
	local sql="$1"
	if [[ -z "$sql" ]]; then
		echo "Error: SQL string is empty." >&2
		return 2
	fi
	echo "-> Running inline SQL"
	if [[ $DRY_RUN -eq 1 ]]; then
		echo "DRY: docker compose -f $COMPOSE_FILE exec -T mysql mysql -u $USER -p*** -D $DB --show-warnings --verbose -e '<SQL>'"
		return 0
	fi
	docker compose -f "$COMPOSE_FILE" exec -T mysql "${MYSQL_ARGS[@]}" -e "$sql"
}

run_mysql_stdin() {
	echo "-> Running SQL from stdin"
	if [[ $DRY_RUN -eq 1 ]]; then
		echo "DRY: docker compose -f $COMPOSE_FILE exec -T mysql mysql -u $USER -p*** -D $DB --show-warnings --verbose < stdin"
		return 0
	fi
	docker compose -f "$COMPOSE_FILE" exec -T mysql "${MYSQL_ARGS[@]}" < "$STDIN_FILE"
}

if [[ $STDIN_PRESENT -eq 1 ]]; then
	run_mysql_stdin
	exit $?
fi

if [[ -n "$FILE" ]]; then
	run_mysql_file "$FILE"
	exit $?
fi

if [[ -n "$SQL" ]]; then
	run_mysql_sql "$SQL"
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

echo "Error: must provide -f FILE, -c SQL, -m DIR, or stdin" >&2
usage
exit 2
