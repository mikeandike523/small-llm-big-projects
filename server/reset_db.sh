#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_SQL="$SCRIPT_DIR/run_sql.sh"

usage() {
	cat <<USAGE
Usage: $(basename "$0") [options]

Reset this project's MySQL database schema objects (views, triggers, events,
routines, tables) using run_sql.sh.

Defaults match run_sql.sh:
  DB=${MYSQL_DATABASE:-slbp}
  USER=${MYSQL_USER:-slbp}
  PASSWORD=${MYSQL_PASSWORD:-slbp}

Options:
  -d DATABASE  Optional database override (default: \$MYSQL_DATABASE or slbp)
  -u USER      Optional user override (default: \$MYSQL_USER or slbp)
  -P PASSWORD  Optional password override (default: \$MYSQL_PASSWORD or slbp)
  -n           Dry-run: print planned SQL without executing
  -y           Skip interactive confirmation prompt
  --help       Show this help
USAGE
}

DB="${MYSQL_DATABASE:-slbp}"
USER="${MYSQL_USER:-slbp}"
PASSWORD="${MYSQL_PASSWORD:-slbp}"
DRY_RUN=0
SKIP_CONFIRM=0

while [[ $# -gt 0 ]]; do
	case "$1" in
		-d) DB="$2"; shift 2;;
		-u) USER="$2"; shift 2;;
		-P) PASSWORD="$2"; shift 2;;
		-n) DRY_RUN=1; shift 1;;
		-y) SKIP_CONFIRM=1; shift 1;;
		--help) usage; exit 0;;
		*) echo "Unknown arg: $1" >&2; usage; exit 2;;
	esac
done

if [[ ! -x "$RUN_SQL" ]]; then
	echo "Error: run_sql.sh not found or not executable at $RUN_SQL" >&2
	exit 2
fi

if [[ -z "$DB" ]]; then
	echo "Error: database name is empty." >&2
	exit 2
fi

case "$DB" in
	mysql|information_schema|performance_schema|sys)
		echo "Refusing to reset system schema: $DB" >&2
		exit 2
		;;
esac

echo "Target database: $DB"
echo "Target user: $USER"

if [[ "${CI:-}" != "true" && $SKIP_CONFIRM -eq 0 && $DRY_RUN -eq 0 ]]; then
	read -r -p "Type 'reset' to continue: " confirm
	if [[ "$confirm" != "reset" ]]; then
		echo "Aborted."
		exit 0
	fi
fi

query_sql() {
	local sql="$1"
	"$RUN_SQL" -d "$DB" -u "$USER" -P "$PASSWORD" -q -B -c "$sql"
}

sql_ident() {
	local ident="$1"
	printf '`%s`' "${ident//\`/\`\`}"
}

mapfile -t views < <(query_sql "SELECT TABLE_NAME FROM information_schema.VIEWS WHERE TABLE_SCHEMA = DATABASE() ORDER BY TABLE_NAME;")
mapfile -t triggers < <(query_sql "SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = DATABASE() ORDER BY TRIGGER_NAME;")
mapfile -t events < <(query_sql "SELECT EVENT_NAME FROM information_schema.EVENTS WHERE EVENT_SCHEMA = DATABASE() ORDER BY EVENT_NAME;")
mapfile -t procs < <(query_sql "SELECT ROUTINE_NAME FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = DATABASE() AND ROUTINE_TYPE = 'PROCEDURE' ORDER BY ROUTINE_NAME;")
mapfile -t funcs < <(query_sql "SELECT ROUTINE_NAME FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = DATABASE() AND ROUTINE_TYPE = 'FUNCTION' ORDER BY ROUTINE_NAME;")
mapfile -t tables < <(query_sql "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_NAME;")

echo "Discovered objects:"
echo "  found ${#views[@]} views"
echo "  found ${#triggers[@]} triggers"
echo "  found ${#events[@]} events"
echo "  found ${#procs[@]} procedures"
echo "  found ${#funcs[@]} functions"
echo "  found ${#tables[@]} tables"

if [[ $DRY_RUN -eq 1 ]]; then
	echo "Dry-run plan:"
	for name in "${views[@]}"; do
		echo "  DROP VIEW IF EXISTS $(sql_ident "$DB").$(sql_ident "$name");"
	done
	for name in "${triggers[@]}"; do
		echo "  DROP TRIGGER IF EXISTS $(sql_ident "$DB").$(sql_ident "$name");"
	done
	for name in "${events[@]}"; do
		echo "  DROP EVENT IF EXISTS $(sql_ident "$DB").$(sql_ident "$name");"
	done
	for name in "${procs[@]}"; do
		echo "  DROP PROCEDURE IF EXISTS $(sql_ident "$DB").$(sql_ident "$name");"
	done
	for name in "${funcs[@]}"; do
		echo "  DROP FUNCTION IF EXISTS $(sql_ident "$DB").$(sql_ident "$name");"
	done
	for name in "${tables[@]}"; do
		echo "  DROP TABLE IF EXISTS $(sql_ident "$DB").$(sql_ident "$name");"
	done
	echo "Reset complete (dry-run)."
	exit 0
fi

fk_checks_disabled=0
reenable_fk_checks() {
	if [[ $fk_checks_disabled -eq 1 ]]; then
		"$RUN_SQL" -d "$DB" -u "$USER" -P "$PASSWORD" -q -c "SET FOREIGN_KEY_CHECKS = 1;" >/dev/null 2>&1 || true
	fi
}
trap reenable_fk_checks EXIT

echo "Disabling foreign key checks..."
"$RUN_SQL" -d "$DB" -u "$USER" -P "$PASSWORD" -q -c "SET FOREIGN_KEY_CHECKS = 0; SET SQL_SAFE_UPDATES = 0;"
fk_checks_disabled=1

echo "Deleting views..."
for name in "${views[@]}"; do
	query_sql "DROP VIEW IF EXISTS $(sql_ident "$DB").$(sql_ident "$name");" >/dev/null
done

echo "Deleting triggers..."
for name in "${triggers[@]}"; do
	query_sql "DROP TRIGGER IF EXISTS $(sql_ident "$DB").$(sql_ident "$name");" >/dev/null
done

echo "Deleting events..."
for name in "${events[@]}"; do
	query_sql "DROP EVENT IF EXISTS $(sql_ident "$DB").$(sql_ident "$name");" >/dev/null
done

echo "Deleting procedures..."
for name in "${procs[@]}"; do
	query_sql "DROP PROCEDURE IF EXISTS $(sql_ident "$DB").$(sql_ident "$name");" >/dev/null
done

echo "Deleting functions..."
for name in "${funcs[@]}"; do
	query_sql "DROP FUNCTION IF EXISTS $(sql_ident "$DB").$(sql_ident "$name");" >/dev/null
done

echo "Deleting tables..."
for name in "${tables[@]}"; do
	query_sql "DROP TABLE IF EXISTS $(sql_ident "$DB").$(sql_ident "$name");" >/dev/null
done

echo "Re-enabling foreign key checks..."
"$RUN_SQL" -d "$DB" -u "$USER" -P "$PASSWORD" -q -c "SET FOREIGN_KEY_CHECKS = 1;"
fk_checks_disabled=0

echo "Reset complete."
