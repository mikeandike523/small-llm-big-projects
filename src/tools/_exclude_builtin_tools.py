# Exclude specific built-in tools from loading and/or testing.
#
# Keys are tool names exactly as they appear in the tool's DEFINITION (function.name).
# Values are dicts with optional boolean flags:
#
#   "loading": True  -- omit the tool from ALL_TOOL_DEFINITIONS and _TOOL_MAP at startup,
#                       so the LLM never sees or calls it.
#   "testing": True  -- skip the tool's test module in tool_tests/run.py.
#
# Both flags are independent; a tool can be excluded from testing while still being loaded,
# or vice-versa.
#
# Example:
#   EXCLUDE: dict[str, dict] = {
#       "brave_web_search": {"loading": True, "testing": True},
#       "basic_web_request": {"testing": True},
#   }

EXCLUDE: dict[str, dict] = {
    "load_skill_files_from_url_to_session_memory":{
        "loading":True,
        "testing":True
    }
}
