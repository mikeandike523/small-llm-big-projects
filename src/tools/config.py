"""Overall configuration for the built-in tools.

Central place for tunable constants that affect tool behavior across the board.
Keep this module dependency-free so any tool can import it cheaply.
"""

from __future__ import annotations

# Maximum number of characters (columns) any single line of a tool's output may
# contain. Lines longer than this are truncated by truncate_long_lines() in the
# central execute_tool() chokepoint, with a "[... N more bytes]" marker appended.
#
# Deliberately set far above normal source-line lengths -- 500 columns is already
# well beyond anything written by hand. The point is purely to stop pathological
# single-line content (minified JS, base64 blobs, compiled WASM checked into git,
# LFS-tracked binaries, etc.) from flooding the context window via tools like
# search_filesystem_by_regex or read_text_file.
#
# There is intentionally no per-call escape hatch. If output is truncated, the
# agent should adapt -- read the file another way, narrow the tool arguments, or
# fetch a different resource -- rather than ask for more columns.
#
# Set to 0 to disable column truncation entirely (see truncate_long_lines).
TOOL_OUTPUT_MAX_COLUMNS = 500
