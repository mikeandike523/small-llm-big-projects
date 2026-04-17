#!/bin/bash

dn="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"
cd "$dn/../server"

STRUCTURE_DIR="./migrations/structure"
SEED_DIR="./migrations/seed"

run_sql() {
  local file="$1"
  echo "  → Running: $file"
  bash ./run_sql.sh -f "$file"
}

try_run() {
  local dir="$1" version="$2"
  local path
  path=$(printf "%s/v%d.sql" "$dir" "$version")
  if [[ -f "$path" ]]; then
    run_sql "$path"
  else
    echo "  ↷ Skipped: $path"
  fi
}

# Collect all version numbers from both dirs
mapfile -t versions < <(
  find "$STRUCTURE_DIR" "$SEED_DIR" -name 'v*.sql' 2>/dev/null \
    | grep -oP '(?<=v)\d+(?=\.sql)' \
    | sort -un
)

if [[ ${#versions[@]} -eq 0 ]]; then
  echo "No migration files found."
  exit 1
fi

echo "Running migrations (versions: ${versions[*]})..."
echo

for v in "${versions[@]}"; do
  echo "── v$v ──"
  try_run "$STRUCTURE_DIR" "$v"
  try_run "$SEED_DIR" "$v"
  echo
done

echo "Done."