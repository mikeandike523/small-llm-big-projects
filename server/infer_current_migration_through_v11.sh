#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ANSI color codes for rich terminal output
GREEN='\033[0;32m'
BOLD_GREEN='\033[1;32m'
RED='\033[0;31m'
BOLD_RED='\033[1;31m'
CYAN='\033[0;36m'
BOLD_CYAN='\033[1;36m'
YELLOW='\033[0;33m'
BOLD_YELLOW='\033[1;33m'
MAGENTA='\033[0;35m'
BOLD_MAGENTA='\033[1;35m'
NC='\033[0m' # No Color
BOLD='\033[1m'

usage() {
	cat <<EOF
Usage: $(basename "$0") [options]

Determines the current migration level by checking the database schema.
Credentials are resolved automatically via run_sql.sh.

Options:
	--json       Output version as raw number (for scripting)
	--quiet      Suppress informational output
	--help       Show this help

Examples:
	$(basename "$0")
	$(basename "$0") --json
EOF
}

# defaults
JSON_MODE=0
QUIET_MODE=0

while [[ $# -gt 0 ]]; do
	case "$1" in
		--json) JSON_MODE=1; shift 1;;
		--quiet) QUIET_MODE=1; shift 1;;
		--help) usage; exit 0;;
		*) echo "Unknown arg: $1" >&2; usage; exit 2;;
	esac
done

# Helper function to run SQL via run_sql.sh
# Always passes -q to run_sql.sh so its "-> Running inline SQL" line
# doesn't pollute stdout (which gets captured by $() callers).
# Our own progress message goes to stderr so callers can suppress it
# with 2>/dev/null without losing the actual SQL result.
run_sql() {
	local sql="$1"
	local result

	if [[ $QUIET_MODE -eq 0 ]]; then
		echo -e "${BOLD_CYAN}🔍 Running SQL:${NC} ${CYAN}$sql${NC}" >&2
	fi
	result=$($SCRIPT_DIR/run_sql.sh -B -q -c "$sql") || true
	if [[ $QUIET_MODE -eq 0 ]]; then
		echo -e "${BOLD_CYAN}🔍 SQL result:${NC} '${result}'" >&2
	fi
	echo "$result"
}

# Helper function to check if a table exists
table_exists() {
	local table_name="$1"
	local result
	if [[ $QUIET_MODE -eq 0 ]]; then
		echo -e "${BOLD_YELLOW}📊 Checking for table:${NC} ${MAGENTA}$table_name${NC}"
	fi
	result=$(run_sql "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = '$table_name');" || echo "0")
	if [[ "$result" == "1" ]]; then
		return 0
	else
		return 1
	fi
}

# Print migration level being checked
print_checking_for() {
	local level="$1"
	if [[ $QUIET_MODE -eq 0 ]]; then
		echo -e "${BOLD_YELLOW}🔍 Checking for migration level:${NC} ${BOLD_CYAN}v$level${NC}"
	fi
}

# Parse the highest structure migration version from directory
# === DEBUG: Quick connectivity test ===
if [[ $QUIET_MODE -eq 0 ]]; then
	echo -e "${BOLD_MAGENTA}🧪 DEBUG: Testing SQL connection...${NC}" >&2
fi
debug_result=$(run_sql "SELECT 1 AS ok;" || echo "FAILED")
if [[ $QUIET_MODE -eq 0 ]]; then
	echo -e "${BOLD_MAGENTA}🧪 DEBUG: SELECT 1 result = '${debug_result}'${NC}" >&2
fi
# === END DEBUG ===
get_max_structure_version() {
	local max_version=0
	for file in "$SCRIPT_DIR/migrations/structure"/v*.sql; do
		if [[ -f "$file" ]]; then
			version=$(basename "$file" | sed 's/v\([0-9]*\)\.sql/\1/' | sed 's/[^0-9]//g')
			if [[ -n "$version" && "$version" -gt "$max_version" ]]; then
				max_version=$version
			fi
		fi
	done
	echo "$max_version"
}

# Parse the highest seed migration version from directory
get_max_seed_version() {
	local max_version=0
	for file in "$SCRIPT_DIR/migrations/seed"/v*.sql; do
		if [[ -f "$file" ]]; then
			version=$(basename "$file" | sed 's/v\([0-9]*\)\.sql/\1/' | sed 's/[^0-9]//g')
			if [[ -n "$version" && "$version" -gt "$max_version" ]]; then
				max_version=$version
			fi
		fi
	done
	echo "$max_version"
}

# Main logic
MAX_STRUCTURE_VERSION=$(get_max_structure_version)
MAX_SEED_VERSION=$(get_max_seed_version)

if [[ $QUIET_MODE -eq 0 && $JSON_MODE -eq 0 ]]; then
	echo -e "${BOLD_GREEN}📊 Max available structure migration version: v$MAX_STRUCTURE_VERSION${NC}"
	echo -e "${BOLD_GREEN}📊 Max available seed migration version: v$MAX_SEED_VERSION${NC}"
fi

# Check for schema version table first (preferred method)
if table_exists "schema_migrations"; then
	if [[ $QUIET_MODE -eq 0 && $JSON_MODE -eq 0 ]]; then
		echo -e "${BOLD_CYAN}✅ Found schema_migrations table${NC}"
	fi
	print_checking_for "schema_migrations"
	LATEST_VERSION=$(run_sql "SELECT MAX(version) FROM schema_migrations;" || echo "")
	if [[ -n "$LATEST_VERSION" && "$LATEST_VERSION" != "NULL" ]]; then
		if [[ $JSON_MODE -eq 1 ]]; then
			echo "$LATEST_VERSION"
		else
			echo -e "${BOLD_GREEN}✅ Current migration level: v$LATEST_VERSION (from schema_migrations table)${NC}"
		fi
		exit 0
	fi
fi

# Fallback: infer from table existence (v11 is highest known)
# Check for session_meta (v11)
if table_exists "session_meta"; then
	if [[ $JSON_MODE -eq 1 ]]; then
		echo "11"
	else
		echo -e "${BOLD_GREEN}✅ Current migration level: v11 (session_meta table exists)${NC}"
	fi
	exit 0
fi

# Check for sessions (v10)
if table_exists "sessions"; then
	if [[ $JSON_MODE -eq 1 ]]; then
		echo "10"
	else
		echo -e "${BOLD_GREEN}✅ Current migration level: v10 (sessions table exists)${NC}"
	fi
	exit 0
fi

# Check for file_snapshots (v9)
if table_exists "file_snapshots"; then
	if [[ $JSON_MODE -eq 1 ]]; then
		echo "9"
	else
		echo -e "${BOLD_GREEN}✅ Current migration level: v9 (file_snapshots table exists)${NC}"
	fi
	exit 0
fi

# Profile table (v6) is dropped in v8, but if profiles table exists (or known_providers exists)
if table_exists "profiles"; then
	if [[ $JSON_MODE -eq 1 ]]; then
		echo "6"
	else
		echo -e "${BOLD_GREEN}✅ Current migration level: v6 (profiles table exists)${NC}"
	fi
	exit 0
fi

# Check for known_providers (v1)
if table_exists "known_providers"; then
	if [[ $JSON_MODE -eq 1 ]]; then
		echo "1"
	else
		echo -e "${BOLD_GREEN}✅ Current migration level: v1 (known_providers table exists)${NC}"
	fi
	exit 0
fi

# Check for kv_store (v2)
if table_exists "kv_store"; then
	if [[ $JSON_MODE -eq 1 ]]; then
		echo "2"
	else
		echo -e "${BOLD_GREEN}✅ Current migration level: v2 (kv_store exists)${NC}"
	fi
	exit 0
fi

# No migration detected
if [[ $JSON_MODE -eq 1 ]]; then
	echo "0"
else
	echo -e "${BOLD_RED}❌ No migrations detected - database may be empty or migrations not applied${NC}"
fi

exit 0
