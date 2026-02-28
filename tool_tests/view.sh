#!/bin/bash
# Serve the test_results/ static site locally and open it in the browser.
# Run ./tool_tests/run_all.sh first to generate the results.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ ! -d "$REPO_ROOT/test_results" ]; then
  echo "No test_results/ directory found. Run ./tool_tests/run_all.sh first."
  exit 1
fi
exec "$REPO_ROOT/python_in_env.sh" "$REPO_ROOT/tool_tests/_view_server.py" "$@"
