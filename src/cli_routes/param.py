import json

import click
from termcolor import colored

from src.data import get_pool
from src.cli_obj import cli
from src.utils.sql.kv_manager import KVManager
from src.utils.profile_utils import get_active_profile, _kv_prefix

_ALLOWED_PARAMS = {
    "model.temperature",
    "model.top_p",
    "model.top_k",
    "model.max_tokens",
    "model.compaction_max_tokens",
    "model.watchdog_max_tokens",
    "model.title_summary_max_tokens",
    "model.request_extra_params",
    "model.default_irat",
    "system.return_value_max_chars",
    "system.assistant_strip_truncation_chars",
}

_PARAM_DOCS = {
    "model.temperature": {
        "type": "float (0.0 - 2.0)",
        "description": (
            "Controls randomness in generation. "
            "0.0 is fully deterministic (always picks the most likely token). "
            "2.0 is very random. Typical values: 0.2 - 0.8."
        ),
    },
    "model.top_p": {
        "type": "float (0.0 - 1.0)",
        "description": (
            "Nucleus sampling threshold. "
            "Only the smallest set of tokens whose cumulative probability "
            "is <= top_p are considered at each step. "
            "1.0 disables nucleus sampling."
        ),
    },
    "model.top_k": {
        "type": "integer > 0",
        "description": (
            "Top-K sampling. Limits the token candidate pool to the K "
            "most probable tokens at each step."
        ),
    },
    "model.max_tokens": {
        "type": "integer > 0",
        "description": (
            "Maximum number of tokens to generate in a single response. "
            "The model may stop earlier if it produces an end-of-sequence token."
        ),
    },
    "model.compaction_max_tokens": {
        "type": "integer > 0",
        "description": (
            "Maximum tokens for the out-of-band compaction LLM call that summarises "
            "completed todo-item steps. "
            "When not set, falls back to model.max_tokens (or the model default if "
            "that is also unset). Set this to a small value (e.g. 300) to keep "
            "compaction summaries short."
        ),
    },
    "model.watchdog_max_tokens": {
        "type": "integer > 0",
        "description": (
            "Maximum tokens for the host_shell hang-watchdog LLM calls (Stage 1 "
            "triage, Stage 1b extension estimate, Stage 2 input injection). "
            "When not set, falls back to model.max_tokens (or the model default). "
            "These calls only need a few tokens (a single word or short string), "
            "so a small value such as 16-64 is sufficient."
        ),
    },
    "model.title_summary_max_tokens": {
        "type": "integer > 0",
        "description": (
            "Maximum tokens for the out-of-band LLM call that generates a short "
            "task title for each turn bubble in the UI. "
            "When not set, falls back to model.max_tokens (or the model default). "
            "For instruct models a small value (e.g. 20-40) is sufficient. "
            "Thinking models may spend extra tokens on reasoning before outputting "
            "the title; display truncation (TITLE_MAX_CHARS) handles overflow."
        ),
    },
    "model.default_irat": {
        "type": "bool (true/false)",
        "description": (
            "Default value for --interim-response-as-thinking (--irat) when creating a "
            "new session. Set to true when using a model that does not produce native "
            "reasoning tokens but narrates its thinking through text output -- irat "
            "redirects that interim text into the thinking panel instead of a char-count "
            "bubble. Typically this should match the active model. If not set, defaults to false."
        ),
    },
    "model.request_extra_params": {
        "type": "JSON object",
        "description": (
            "Extra parameters merged directly into every LLM API request payload. "
            "Must be a valid JSON object (curly-brace delimited). "
            "Useful for non-standard provider params such as "
            "{\"reasoning\":{\"effort\":\"low\"}} or {\"provider\":{\"order\":[\"Fireworks\"]}}. "
            "Keys in this object take precedence over other model params."
        ),
    },
    "system.return_value_max_chars": {
        "type": "integer > 0",
        "description": (
            "When a tool return value exceeds this many characters, it is "
            "automatically truncated to a preview stub and the full content "
            "is saved under a session memory key (stubs.*) so the LLM can "
            "retrieve it in chunks if needed."
        ),
    },
    "system.assistant_strip_truncation_chars": {
        "type": "integer >= 0",
        "description": (
            "Controls how the assistant's own interim text content "
            "(the text the LLM writes alongside tool calls) is handled "
            "when the conversation history is stripped down for a retry "
            "after a timeout or context-limit error.\n"
            "  0       : fully omit interim assistant content.\n"
            "  N > 0   : truncate interim content to N characters and append '... (M more chars)'.\n"
            "  not set : leave interim assistant content unchanged (default)."
        ),
    },
}


def _parse_and_validate(name: str, raw_value: str):
    """Parse and validate a param value. Returns the typed value or raises click.BadParameter."""
    if name not in _ALLOWED_PARAMS:
        raise click.BadParameter(
            f"Unknown param '{name}'. Allowed: {', '.join(sorted(_ALLOWED_PARAMS))}",
            param_hint="name",
        )
    try:
        if name == "model.default_irat":
            if raw_value.lower() not in ("true", "false"):
                raise click.BadParameter("model.default_irat must be 'true' or 'false'", param_hint="value")
            return raw_value.lower() == "true"
        elif name == "model.request_extra_params":
            try:
                value = json.loads(raw_value)
            except json.JSONDecodeError as exc:
                raise click.BadParameter(
                    f"model.request_extra_params must be valid JSON: {exc}", param_hint="value"
                )
            if not isinstance(value, dict):
                raise click.BadParameter(
                    "model.request_extra_params must be a JSON object (got "
                    + type(value).__name__ + ")",
                    param_hint="value",
                )
            return value
        elif name == "model.top_k":
            value = int(raw_value)
            if value <= 0:
                raise click.BadParameter("model.top_k must be > 0", param_hint="value")
            return value
        elif name == "model.max_tokens":
            value = int(raw_value)
            if value <= 0:
                raise click.BadParameter("model.max_tokens must be > 0", param_hint="value")
            return value
        elif name == "model.compaction_max_tokens":
            value = int(raw_value)
            if value <= 0:
                raise click.BadParameter("model.compaction_max_tokens must be > 0", param_hint="value")
            return value
        elif name == "model.watchdog_max_tokens":
            value = int(raw_value)
            if value <= 0:
                raise click.BadParameter("model.watchdog_max_tokens must be > 0", param_hint="value")
            return value
        elif name == "model.title_summary_max_tokens":
            value = int(raw_value)
            if value <= 0:
                raise click.BadParameter("model.title_summary_max_tokens must be > 0", param_hint="value")
            return value
        elif name == "system.return_value_max_chars":
            value = int(raw_value)
            if value <= 0:
                raise click.BadParameter("system.return_value_max_chars must be > 0", param_hint="value")
            return value
        elif name == "system.assistant_strip_truncation_chars":
            value = int(raw_value)
            if value < 0:
                raise click.BadParameter("system.assistant_strip_truncation_chars must be >= 0", param_hint="value")
            return value
        else:
            value = float(raw_value)
            if name == "model.temperature" and not (0.0 <= value <= 2.0):
                raise click.BadParameter("model.temperature must be between 0.0 and 2.0", param_hint="value")
            if name == "model.top_p" and not (0.0 <= value <= 1.0):
                raise click.BadParameter("model.top_p must be between 0.0 and 1.0", param_hint="value")
            return value
    except ValueError:
        int_params = {"model.top_k", "model.max_tokens", "model.compaction_max_tokens", "model.watchdog_max_tokens", "model.title_summary_max_tokens", "system.return_value_max_chars", "system.assistant_strip_truncation_chars"}
        type_hint = "integer" if name in int_params else "float"
        raise click.BadParameter(f"value for '{name}' must be a {type_hint}", param_hint="value")


@cli.group()
def param():
    ...

@param.command("list")
@click.option("--available", is_flag=True, default=False, help="List all available params with their types and descriptions.")
def sub_cmd_list(available):
    if available:
        entries = sorted(_PARAM_DOCS.items())
        for i, (name, doc) in enumerate(entries):
            if i:
                click.echo("")
            click.echo(colored(name, "blue") + f"  ({doc['type']})")
            for line in doc["description"].splitlines():
                click.echo(f"  {line}")
        return

    click.echo('')
    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        profile = get_active_profile(kv)
        prefix = _kv_prefix(profile)
        params_prefix = prefix + "params."
        keys = kv.list_keys(prefix=params_prefix)
        if not keys:
            click.echo(f"No params set.  (profile: {profile})")
        else:
            click.echo(f"(profile: {profile})")
        for i, key in enumerate(keys):
            is_last = i == len(keys) - 1
            display_key = key[len(params_prefix):]
            val = kv.get_value(key)
            print(f"""
{colored(display_key,'blue')}:

{json.dumps(val, indent=2)}
""".strip() + ("\n\n" if not is_last else ""))

@param.command(name="set")
@click.argument("name", type=str)
@click.argument("value", type=str)
def sub_cmd_set(name, value):
    """
    Set a generation parameter (temperature, top_p, top_k).
    """
    typed_value = _parse_and_validate(name, value)
    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        profile = get_active_profile(kv)
        prefix = _kv_prefix(profile)
        kv.set_value(f"{prefix}params.{name}", typed_value)
        conn.commit()
    click.echo(f"Set {name} = {typed_value}  (profile: {profile})")


@param.command(name="show")
def sub_cmd_show():
    """
    Show all currently set generation parameters.
    """
    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        profile = get_active_profile(kv)
        prefix = _kv_prefix(profile)
        params_prefix = prefix + "params."
        keys = kv.list_keys(prefix=params_prefix)
        if not keys:
            click.echo(f"No params set.  (profile: {profile})")
            return
        for key in keys:
            param_name = key[len(params_prefix):]
            val = kv.get_value(key)
            click.echo(f"{param_name} = {val}")
    click.echo(f"(profile: {profile})")


@param.command(name="unset")
@click.argument("name", type=str)
def sub_cmd_unset(name):
    """
    Remove a generation parameter.
    """
    if name not in _ALLOWED_PARAMS:
        raise click.BadParameter(
            f"Unknown param '{name}'. Allowed: {', '.join(sorted(_ALLOWED_PARAMS))}",
            param_hint="name",
        )
    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        profile = get_active_profile(kv)
        prefix = _kv_prefix(profile)
        if not kv.exists(f"{prefix}params.{name}"):
            click.echo(f"{name} is not set.  (profile: {profile})")
            return
        kv.delete_value(f"{prefix}params.{name}")
        conn.commit()
    click.echo(f"Unset {name}  (profile: {profile})")


@param.command(name="manual")
def sub_cmd_manual():
    """
    Print documentation for every available parameter.
    """
    entries = sorted(_PARAM_DOCS.items())
    for i, (name, doc) in enumerate(entries):
        if i:
            click.echo("")
        click.echo(colored(name, "blue") + f"  ({doc['type']})")
        # Indent each line of the description by two spaces
        for line in doc["description"].splitlines():
            click.echo(f"  {line}")
