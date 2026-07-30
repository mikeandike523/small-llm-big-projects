#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_SQL="$SCRIPT_DIR/run_sql.sh"

# ── ANSI color codes ─────────────────────────────────────────────────────────
GREEN='\033[0;32m'
BOLD_GREEN='\033[1;32m'
RED='\033[0;31m'
BOLD_RED='\033[1;31m'
CYAN='\033[0;36m'
BOLD_CYAN='\033[1;36m'
YELLOW='\033[0;33m'
BOLD_YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# ── Usage ────────────────────────────────────────────────────────────────────
usage() {
	cat <<EOF
Usage: $(basename "$0") <subcommand> [args]

Subcommands:
  show                      Show the current structure_version and seed_version,
                            alongside the max version available on disk.
  up                        Run all pending migrations (structure then seed,
                            interleaved by version number).
  force-set-version S V     Set the migration version table directly to the
                            given structure_version (S) and seed_version (V).
                            Both must be non-negative integers.

Options:
  --help                    Show this help message.

Credentials are resolved automatically via run_sql.sh.
EOF
}

# ── Prerequisite check ───────────────────────────────────────────────────────
if [[ ! -x "$RUN_SQL" ]]; then
	echo -e "${BOLD_RED}Error: run_sql.sh not found or not executable at $RUN_SQL${NC}" >&2
	exit 2
fi

# ── Helper: run an SQL query silently and return the raw result ──────────────
# Uses -B -q for batch mode, quiet output (tab-separated, no column headers).
# All arguments are passed directly to run_sql.sh.
run_sql_query() {
	"$RUN_SQL" -B -q -c "$1"
}

# ── Helper: run an SQL statement quietly (no batch mode needed) ──────────────
run_sql_quiet() {
	"$RUN_SQL" -q -c "$1"
}

# ── Helper: run a SQL file (migration) with full output ──────────────────────
run_sql_file() {
	"$RUN_SQL" -f "$1"
}

# ── ensure_migration_version_table ──────────────────────────────────────────
# Makes sure the migration_version table and its single tracking row exist.
# Safe to call repeatedly — idempotent by design.
ensure_migration_version_table() {
	local sql
	# Read the multi-line SQL via heredoc for readability.
	# The table has a single row (id=1) with independent columns for
	# structure and seed versions, both defaulting to 0.
	sql="CREATE TABLE IF NOT EXISTS migration_version (
  id INT PRIMARY KEY,
  structure_version INT NOT NULL DEFAULT 0,
  seed_version INT NOT NULL DEFAULT 0
);"
	run_sql_quiet "$sql"

	sql="INSERT IGNORE INTO migration_version (id, structure_version, seed_version)
VALUES (1, 0, 0);"
	run_sql_quiet "$sql"
}

# ── get_current_versions ─────────────────────────────────────────────────────
# Reads the current structure_version and seed_version from the database.
# Populates the two global variables passed by name (bash nameref / declare -n).
# Must be called AFTER ensure_migration_version_table.
get_current_versions() {
	local -n out_structure=$1
	local -n out_seed=$2
	local result

	# Batch-mode query returns tab-separated values: "S\tV"
	result=$(run_sql_query "SELECT structure_version, seed_version FROM migration_version WHERE id=1;")

	# Parse the two numbers out of the tab-delimited result.
	# IFS=$'\t' splits on the tab; -r prevents backslash interpretation.
	IFS=$'\t' read -r out_structure out_seed <<< "$result"

	# Defensive: strip any accidental whitespace from the parsed values.
	out_structure="${out_structure//[[:space:]]/}"
	out_seed="${out_seed//[[:space:]]/}"
}

# ── get_max_version_in_dir ───────────────────────────────────────────────────
# Scans a directory for v*.sql files and returns the highest version number.
# Echoes 0 if no files found.
get_max_version_in_dir() {
	local dir="$1"
	local max_version=0
	local version

	# Use a plain glob + loop.  nullglob is NOT set here so that if no files
	# match, the loop simply doesn't execute (instead of expanding the literal
	# "v*.sql" string).
	for file in "$dir"/v*.sql; do
		# Skip if glob didn't match anything (the literal pattern itself).
		[[ -f "$file" ]] || continue

		# Extract the numeric part: "v123.sql" → "123"
		version=$(basename "$file" .sql)
		version="${version#v}"
		# Sanity check: make sure we got a number.
		if [[ "$version" =~ ^[0-9]+$ ]] && (( version > max_version )); then
			max_version=$version
		fi
	done

	echo "$max_version"
}

# ── print_version_with_color ─────────────────────────────────────────────────
# Prints a version number with color: amber if behind, green if 0 (also behind),
# cyan if up-to-date (equal or ahead of max).
_print_version_status() {
	local current=$1
	local max=$2
	if (( current == 0 )) && (( max == 0 )); then
		echo -en "${GREEN}${current}${NC}"
	elif (( current >= max )); then
		echo -en "${BOLD_CYAN}${current}${NC}"
	else
		echo -en "${BOLD_YELLOW}${current}${NC}"
	fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# Subcommand: show
# ═══════════════════════════════════════════════════════════════════════════════
cmd_show() {
	ensure_migration_version_table

	local current_structure current_seed
	get_current_versions current_structure current_seed

	local max_structure max_seed
	max_structure=$(get_max_version_in_dir "$SCRIPT_DIR/migrations/structure")
	max_seed=$(get_max_version_in_dir "$SCRIPT_DIR/migrations/seed")

	echo -e "${BOLD_CYAN}Current versions:${NC}"
	echo -e "  structure_version = $(_print_version_status "$current_structure" "$max_structure") ${NC}(max available: ${max_structure})"
	echo -e "  seed_version      = $(_print_version_status "$current_seed" "$max_seed") ${NC}(max available: ${max_seed})"
}

# ═══════════════════════════════════════════════════════════════════════════════
# Subcommand: up
# ═══════════════════════════════════════════════════════════════════════════════
cmd_up() {
	ensure_migration_version_table

	# ── Read current state ─────────────────────────────────────────────────
	local current_structure current_seed
	get_current_versions current_structure current_seed

	# ── Discover available migrations ──────────────────────────────────────
	local max_structure max_seed max_version
	max_structure=$(get_max_version_in_dir "$SCRIPT_DIR/migrations/structure")
	max_seed=$(get_max_version_in_dir "$SCRIPT_DIR/migrations/seed")

	# The loop must cover the larger of the two maxes so we interleave
	# structure → seed for every version N that has at least one file.
	if (( max_structure > max_seed )); then
		max_version=$max_structure
	else
		max_version=$max_seed
	fi

	if (( max_version == 0 )); then
		echo -e "${BOLD_YELLOW}No migration files found in structure/ or seed/.${NC}"
		exit 0
	fi

	# ── Print plan ────────────────────────────────────────────────────────
	echo -e "${BOLD_CYAN}Current versions:${NC}"
	echo -e "  structure_version = $(_print_version_status "$current_structure" "$max_structure")"
	echo -e "  seed_version      = $(_print_version_status "$current_seed" "$max_seed")"
	echo -e "${BOLD_CYAN}Max available:${NC} structure v${max_structure}, seed v${max_seed}"
	echo ""

	# Build a list of planned files so we can preview before running.
	local planned_files=()
	local n
	for (( n = 1; n <= max_version; n++ )); do
		local sfile="$SCRIPT_DIR/migrations/structure/v${n}.sql"
		local efile="$SCRIPT_DIR/migrations/seed/v${n}.sql"

		if [[ -f "$sfile" ]] && (( n > current_structure )); then
			planned_files+=("structure/v${n}.sql")
		fi
		if [[ -f "$efile" ]] && (( n > current_seed )); then
			planned_files+=("seed/v${n}.sql")
		fi
	done

	if (( ${#planned_files[@]} == 0 )); then
		echo -e "${BOLD_GREEN}Already up to date.${NC}"
		exit 0
	fi

	echo -e "${BOLD_CYAN}Planning to run ${#planned_files[@]} migration(s):${NC}"
	for f in "${planned_files[@]}"; do
		echo -e "  ${CYAN}${f}${NC}"
	done
	echo ""

	# ── Execute ───────────────────────────────────────────────────────────
	local ran_any=0
	for (( n = 1; n <= max_version; n++ )); do
		local sfile="$SCRIPT_DIR/migrations/structure/v${n}.sql"
		local efile="$SCRIPT_DIR/migrations/seed/v${n}.sql"

		# --- structure ---
		if [[ -f "$sfile" ]] && (( n > current_structure )); then
			echo -en "${BOLD_CYAN}Running structure/v${n}.sql...${NC} "
			if run_sql_file "$sfile"; then
				echo -e "${BOLD_GREEN}OK${NC}"
				# Update the version immediately after success, so a later
				# failure doesn't cause this file to be re-run on retry.
				run_sql_quiet "UPDATE migration_version SET structure_version = ${n} WHERE id = 1;"
				current_structure=$n
				ran_any=1
				echo -e "  ${GREEN}-> structure_version updated to ${n}${NC}"
			else
				local ec=$?
				echo -e "${BOLD_RED}FAILED${NC}"
				echo -e "${BOLD_RED}Error: structure/v${n}.sql failed (exit code ${ec}). Stopping.${NC}" >&2
				echo -e "${YELLOW}structure_version remains at ${current_structure}. Fix the issue and re-run.${NC}" >&2
				exit $ec
			fi
		fi

		# --- seed ---
		if [[ -f "$efile" ]] && (( n > current_seed )); then
			echo -en "${BOLD_CYAN}Running seed/v${n}.sql...${NC} "
			if run_sql_file "$efile"; then
				echo -e "${BOLD_GREEN}OK${NC}"
				run_sql_quiet "UPDATE migration_version SET seed_version = ${n} WHERE id = 1;"
				current_seed=$n
				ran_any=1
				echo -e "  ${GREEN}-> seed_version updated to ${n}${NC}"
			else
				local ec=$?
				echo -e "${BOLD_RED}FAILED${NC}"
				echo -e "${BOLD_RED}Error: seed/v${n}.sql failed (exit code ${ec}). Stopping.${NC}" >&2
				echo -e "${YELLOW}seed_version remains at ${current_seed}. Fix the issue and re-run.${NC}" >&2
				exit $ec
			fi
		fi
	done

	# ── Final summary ─────────────────────────────────────────────────────
	echo ""
	echo -e "${BOLD_GREEN}Migration complete.${NC}"
	echo -e "  structure_version = ${BOLD_CYAN}${current_structure}${NC}"
	echo -e "  seed_version      = ${BOLD_CYAN}${current_seed}${NC}"
}

# ═══════════════════════════════════════════════════════════════════════════════
# Subcommand: force-set-version
# ═══════════════════════════════════════════════════════════════════════════════
cmd_force_set_version() {
	local new_structure="$1"
	local new_seed="$2"

	# Validate: both must be non-negative integers.
	if [[ ! "$new_structure" =~ ^[0-9]+$ ]]; then
		echo -e "${BOLD_RED}Error: structure_version must be a non-negative integer, got '${new_structure}'${NC}" >&2
		exit 2
	fi
	if [[ ! "$new_seed" =~ ^[0-9]+$ ]]; then
		echo -e "${BOLD_RED}Error: seed_version must be a non-negative integer, got '${new_seed}'${NC}" >&2
		exit 2
	fi

	ensure_migration_version_table

	# Read current values to display what's changing.
	local old_structure old_seed
	get_current_versions old_structure old_seed

	# REPLACE INTO overwrites the row if it exists, inserts if it doesn't.
	run_sql_quiet "REPLACE INTO migration_version (id, structure_version, seed_version) VALUES (1, ${new_structure}, ${new_seed});"

	echo -e "${BOLD_GREEN}Migration version set.${NC}"
	echo -e "  structure_version: ${BOLD_YELLOW}${old_structure}${NC} -> ${BOLD_CYAN}${new_structure}${NC}"
	echo -e "  seed_version:      ${BOLD_YELLOW}${old_seed}${NC} -> ${BOLD_CYAN}${new_seed}${NC}"
}

# ═══════════════════════════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════════════════════════

if [[ $# -eq 0 ]]; then
	usage
	exit 1
fi

SUBCMD="$1"
shift

case "$SUBCMD" in
	show)
		if [[ $# -ne 0 ]]; then
			echo -e "${BOLD_RED}Error: 'show' takes no arguments.${NC}" >&2
			usage
			exit 2
		fi
		cmd_show
		;;
	up)
		if [[ $# -ne 0 ]]; then
			echo -e "${BOLD_RED}Error: 'up' takes no arguments.${NC}" >&2
			usage
			exit 2
		fi
		cmd_up
		;;
	force-set-version)
		if [[ $# -ne 2 ]]; then
			echo -e "${BOLD_RED}Error: 'force-set-version' requires <structure_version> <seed_version>.${NC}" >&2
			usage
			exit 2
		fi
		cmd_force_set_version "$1" "$2"
		;;
	--help)
		usage
		exit 0
		;;
	*)
		echo -e "${BOLD_RED}Error: unknown subcommand '${SUBCMD}'.${NC}" >&2
		usage
		exit 1
		;;
esac