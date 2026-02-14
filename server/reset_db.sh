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

count_views=$(query_sql "SELECT COUNT(*) FROM information_schema.VIEWS WHERE TABLE_SCHEMA = DATABASE();")
count_triggers=$(query_sql "SELECT COUNT(*) FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = DATABASE();")
count_events=$(query_sql "SELECT COUNT(*) FROM information_schema.EVENTS WHERE EVENT_SCHEMA = DATABASE();")
count_procs=$(query_sql "SELECT COUNT(*) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = DATABASE() AND ROUTINE_TYPE = 'PROCEDURE';")
count_funcs=$(query_sql "SELECT COUNT(*) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = DATABASE() AND ROUTINE_TYPE = 'FUNCTION';")
count_tables=$(query_sql "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE';")

echo "Discovered objects:"
echo "  views: $count_views"
echo "  triggers: $count_triggers"
echo "  events: $count_events"
echo "  procedures: $count_procs"
echo "  functions: $count_funcs"
echo "  tables: $count_tables"

drop_views=$(query_sql "SELECT IF(COUNT(*) = 0, '', CONCAT('DROP VIEW IF EXISTS ', GROUP_CONCAT(CONCAT('`', REPLACE(TABLE_SCHEMA, '`', '``'), '`.`', REPLACE(TABLE_NAME, '`', '``'), '`') ORDER BY TABLE_NAME SEPARATOR ', '), ';')) FROM information_schema.VIEWS WHERE TABLE_SCHEMA = DATABASE();")

drop_triggers=$(query_sql "SELECT IF(COUNT(*) = 0, '', GROUP_CONCAT(CONCAT('DROP TRIGGER IF EXISTS `', REPLACE(TRIGGER_SCHEMA, '`', '``'), '`.`', REPLACE(TRIGGER_NAME, '`', '``'), '`;') ORDER BY TRIGGER_NAME SEPARATOR ' ')) FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = DATABASE();")

drop_events=$(query_sql "SELECT IF(COUNT(*) = 0, '', GROUP_CONCAT(CONCAT('DROP EVENT IF EXISTS `', REPLACE(EVENT_SCHEMA, '`', '``'), '`.`', REPLACE(EVENT_NAME, '`', '``'), '`;') ORDER BY EVENT_NAME SEPARATOR ' ')) FROM information_schema.EVENTS WHERE EVENT_SCHEMA = DATABASE();")

drop_procs=$(query_sql "SELECT IF(COUNT(*) = 0, '', GROUP_CONCAT(CONCAT('DROP PROCEDURE IF EXISTS `', REPLACE(ROUTINE_SCHEMA, '`', '``'), '`.`', REPLACE(ROUTINE_NAME, '`', '``'), '`;') ORDER BY ROUTINE_NAME SEPARATOR ' ')) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = DATABASE() AND ROUTINE_TYPE = 'PROCEDURE';")

drop_funcs=$(query_sql "SELECT IF(COUNT(*) = 0, '', GROUP_CONCAT(CONCAT('DROP FUNCTION IF EXISTS `', REPLACE(ROUTINE_SCHEMA, '`', '``'), '`.`', REPLACE(ROUTINE_NAME, '`', '``'), '`;') ORDER BY ROUTINE_NAME SEPARATOR ' ')) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = DATABASE() AND ROUTINE_TYPE = 'FUNCTION';")

drop_tables=$(query_sql "SELECT IF(COUNT(*) = 0, '', CONCAT('DROP TABLE IF EXISTS ', GROUP_CONCAT(CONCAT('`', REPLACE(TABLE_SCHEMA, '`', '``'), '`.`', REPLACE(TABLE_NAME, '`', '``'), '`') ORDER BY TABLE_NAME SEPARATOR ', '), ';')) FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE';")

echo "Drop plan:"
if [[ -n "$drop_views" ]]; then echo "  drop views"; else echo "  no views to drop"; fi
if [[ -n "$drop_triggers" ]]; then echo "  drop triggers"; else echo "  no triggers to drop"; fi
if [[ -n "$drop_events" ]]; then echo "  drop events"; else echo "  no events to drop"; fi
if [[ -n "$drop_procs" ]]; then echo "  drop procedures"; else echo "  no procedures to drop"; fi
if [[ -n "$drop_funcs" ]]; then echo "  drop functions"; else echo "  no functions to drop"; fi
if [[ -n "$drop_tables" ]]; then echo "  drop tables"; else echo "  no tables to drop"; fi

reset_sql=$'SET FOREIGN_KEY_CHECKS = 0;\nSET SQL_SAFE_UPDATES = 0;\n'

if [[ -n "$drop_views" ]]; then
	reset_sql+="$drop_views"
	reset_sql+=$'\n'
fi
if [[ -n "$drop_triggers" ]]; then
	reset_sql+="$drop_triggers"
	reset_sql+=$'\n'
fi
if [[ -n "$drop_events" ]]; then
	reset_sql+="$drop_events"
	reset_sql+=$'\n'
fi
if [[ -n "$drop_procs" ]]; then
	reset_sql+="$drop_procs"
	reset_sql+=$'\n'
fi
if [[ -n "$drop_funcs" ]]; then
	reset_sql+="$drop_funcs"
	reset_sql+=$'\n'
fi
if [[ -n "$drop_tables" ]]; then
	reset_sql+="$drop_tables"
	reset_sql+=$'\n'
fi

reset_sql+=$'SET FOREIGN_KEY_CHECKS = 1;\n'

if [[ $DRY_RUN -eq 1 ]]; then
	echo "Dry-run SQL:"
	echo "$reset_sql"
	echo "Reset complete (dry-run)."
	exit 0
fi

"$RUN_SQL" -d "$DB" -u "$USER" -P "$PASSWORD" -q -c "$reset_sql"

echo "Reset complete."
