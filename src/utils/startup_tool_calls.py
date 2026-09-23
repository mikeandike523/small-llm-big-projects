from __future__ import annotations

from src.utils.tool_calling.arguments import ToolValidationError, validate_tool_args


def validate_startup_tool_calls(calls: object, tool_map: dict) -> str | None:
    """Validate a parsed startup_tool_calls.json value against a session's full tool map.

    tool_map should be the session's FULL tool map (built-ins + unscoped custom
    tools + every skill-scoped plugin's tools, regardless of skill activity) —
    startup tool calls run before any turn/skill-selection happens, so every
    loaded tool is reachable by name, matching how they actually execute (see
    _get_session_tool_map / handle_run_startup_tool_calls).

    Returns an error message describing the first problem found, or None if
    valid. Checked eagerly at session creation so a misconfigured startup
    sequence fails loudly there — the same hard-fail-at-creation guarantee
    custom tools and skills already get — instead of silently degrading into
    a soft "Unknown tool" or "Error executing" string result the first time
    the session actually runs it.

    startup_tool_calls.json is hand-authored by a human with filesystem
    access to the project — writing an entry IS that human's approval for
    it, the same as clicking Approve on an interactive prompt. So
    request_unredacted works exactly as it does in an already-approved
    normal tool call (honored if the target tool allows the bypass at all,
    i.e. hasn't set ALLOW_REQUEST_UNREDACTED = False) — it is not schema-
    validated here since, like any reserved param, it isn't declared in the
    tool's own DEFINITION.
    """
    # Local import: avoids a src.tools <-> src.utils.startup_tool_calls import-time
    # coupling for a single frozenset lookup.
    from src.tools import _RESERVED_TOOL_PARAMS

    if not isinstance(calls, list):
        return "startup_tool_calls.json must contain a JSON array."

    for i, tc_spec in enumerate(calls):
        if not isinstance(tc_spec, dict):
            return f"startup_tool_calls.json entry {i} must be an object."

        name = tc_spec.get("name")
        if not isinstance(name, str) or not name:
            return f"startup_tool_calls.json entry {i} is missing a string 'name'."

        module = tool_map.get(name)
        if module is None:
            return (
                f"startup_tool_calls.json entry {i} references unknown tool {name!r}. "
                "Use the tool's final name (namespaced, if it's a skill-scoped custom "
                "tool)."
            )

        args = tc_spec.get("args", {})
        if not isinstance(args, dict):
            return f"startup_tool_calls.json entry {i} ({name!r}) 'args' must be an object."

        # Reserved params (e.g. request_unredacted) are never declared in a
        # tool's own DEFINITION, so they're excluded from schema validation
        # here — same split execute_tool itself uses (strip, then validate).
        schema_args = {k: v for k, v in args.items() if k not in _RESERVED_TOOL_PARAMS}
        try:
            validate_tool_args(module.DEFINITION, schema_args)
        except ToolValidationError as exc:
            return (
                f"startup_tool_calls.json entry {i} ({name!r}) has invalid args: {exc}"
            )

    return None
