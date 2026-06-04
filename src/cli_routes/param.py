import json

import click
from termcolor import colored

from src.data import get_pool
from src.cli_obj import cli
from src.utils.sql.kv_manager import KVManager
from src.utils.profile_utils import require_active_profile, _kv_prefix
from src.utils.param_registry import ALLOWED_PARAMS as _ALLOWED_PARAMS

_NS_LABELS = {
    "model": "Main agentic loop (streaming calls)",
    "watchdog.model": "Watchdog samplers (YES/NO answers, task titles, skill selection, managed-process triage)",
    "summarizer.model": "Summarizer samplers (subturn compaction, summarize_memory_item tool)",
    "patchrewriter.model": "Patch-rewriter sampler (unified diff repair)",
}

_SUFFIX_DOCS = {
    "temperature": {
        "type": "float (0.0 - 2.0)",
        "description": (
            "Controls randomness in generation. "
            "0.0 is fully deterministic (always picks the most likely token). "
            "2.0 is very random. Typical values: 0.2 - 0.8."
        ),
    },
    "top_p": {
        "type": "float (0.0 - 1.0)",
        "description": (
            "Nucleus sampling threshold. "
            "Only the smallest set of tokens whose cumulative probability "
            "is <= top_p are considered at each step. "
            "1.0 disables nucleus sampling."
        ),
    },
    "top_k": {
        "type": "integer > 0",
        "description": (
            "Top-K sampling. Limits the token candidate pool to the K "
            "most probable tokens at each step."
        ),
    },
    "max_tokens": {
        "type": "integer > 0",
        "description": (
            "Maximum number of tokens to generate in a single response. "
            "The model may stop earlier if it produces an end-of-sequence token."
        ),
    },
    "request_extra_params": {
        "type": "JSON object",
        "description": (
            "Extra parameters merged directly into every API request for this call type. "
            "Must be a valid JSON object (curly-brace delimited). "
            "Applies ONLY to this namespace -- never merged with other namespaces. "
            'Useful for non-standard provider params such as {"reasoning":{"effort":"low"}}.'
        ),
    },
}

_PARAM_DOCS: dict[str, dict] = {}
for _ns in ("model", "watchdog.model", "summarizer.model", "patchrewriter.model"):
    for _suffix, _doc in _SUFFIX_DOCS.items():
        _PARAM_DOCS[f"{_ns}.{_suffix}"] = _doc

# model-only extras
_PARAM_DOCS["model.irat"] = {
    "type": "bool (true/false)",
    "description": (
        "Enable interim-response-as-thinking for all new sessions. "
        "When true, interim assistant content (text produced between tool call rounds) "
        "is redirected into the thinking panel instead of a char-count bubble. "
        "Useful for non-thinking models that narrate reasoning through text output. "
        "Typically set to match the active model. If not set, defaults to false."
    ),
}
_PARAM_DOCS["system.blank_response_retries"] = {
    "type": "integer >= 0",
    "description": (
        "Number of silent LLM retries before injecting a todo-nudge when the model "
        "emits a blank response with no tool calls. "
        "Silent retries do not append anything to conversation history so the model "
        "gets a fresh chance to respond. "
        "Retries are skipped when model.temperature is 0 (deterministic -- retrying would loop forever). "
        "0 = no silent retries, nudge immediately (default). "
        "Typical useful range: 1-2."
    ),
}
_PARAM_DOCS["system.strict_dirty"] = {
    "type": "bool (true/false)",
    "description": (
        "Controls how strictly the dirty-file cache blocks tool calls. "
        "true (default): block if the file has never been read OR has been modified since last read. "
        "false: only block if the file has never been read. "
        "Modifications since last read are allowed through to the approval step. "
        "Useful for models that prefer calling apply_patch multiple times "
        "rather than writing multi-hunk patches, avoiding unnecessary re-read round trips."
    ),
}
_PARAM_DOCS["system.return_value_max_chars"] = {
    "type": "integer > 0",
    "description": (
        "When a tool return value exceeds this many characters, it is "
        "automatically truncated to a preview stub and the full content "
        "is saved under a session memory key (stubs.*) so the LLM can "
        "retrieve it in chunks if needed."
    ),
}


def _suffix(name: str) -> str:
    """Return the last dotted component of a param name (e.g. 'max_tokens')."""
    return name.rsplit(".", 1)[-1]


def _parse_and_validate(name: str, raw_value: str):
    """Parse and validate a param value. Returns the typed value or raises click.BadParameter."""
    if name not in _ALLOWED_PARAMS:
        raise click.BadParameter(
            f"Unknown param '{name}'. Allowed: {', '.join(sorted(_ALLOWED_PARAMS))}",
            param_hint="name",
        )

    suf = _suffix(name)

    if name == "model.irat":
        if raw_value.lower() not in ("true", "false"):
            raise click.BadParameter("model.irat must be 'true' or 'false'", param_hint="value")
        return raw_value.lower() == "true"

    if suf == "request_extra_params":
        try:
            value = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise click.BadParameter(
                f"{name} must be valid JSON: {exc}", param_hint="value"
            )
        if not isinstance(value, dict):
            raise click.BadParameter(
                f"{name} must be a JSON object (got {type(value).__name__})",
                param_hint="value",
            )
        return value

    if name == "system.blank_response_retries":
        try:
            value = int(raw_value)
        except ValueError:
            raise click.BadParameter(
                f"value for '{name}' must be an integer", param_hint="value"
            )
        if value < 0:
            raise click.BadParameter(
                f"value for '{name}' must be >= 0", param_hint="value"
            )
        return value

    if suf in ("top_k", "max_tokens") or name == "system.return_value_max_chars":
        try:
            value = int(raw_value)
        except ValueError:
            raise click.BadParameter(
                f"value for '{name}' must be an integer", param_hint="value"
            )
        if value <= 0:
            raise click.BadParameter(f"value for '{name}' must be > 0", param_hint="value")
        return value

    # float params: temperature, top_p
    try:
        value = float(raw_value)
    except ValueError:
        raise click.BadParameter(
            f"value for '{name}' must be a float", param_hint="value"
        )
    if suf == "temperature" and not (0.0 <= value <= 2.0):
        raise click.BadParameter(
            f"{name} must be between 0.0 and 2.0", param_hint="value"
        )
    if suf == "top_p" and not (0.0 <= value <= 1.0):
        raise click.BadParameter(
            f"{name} must be between 0.0 and 1.0", param_hint="value"
        )
    return value


@cli.group()
def param(): ...


@param.command("list")
@click.option(
    "--available",
    is_flag=True,
    default=False,
    help="List all available params with their types and descriptions.",
)
def sub_cmd_list(available):
    if available:
        # Group by namespace for readability
        from itertools import groupby

        def _ns(n):
            parts = n.split(".")
            if parts[-1] in _SUFFIX_DOCS:
                return ".".join(parts[:-1])
            return n

        entries = sorted(_PARAM_DOCS.items())
        current_ns = None
        for i, (name, doc) in enumerate(entries):
            ns = _ns(name)
            if ns != current_ns:
                current_ns = ns
                label = _NS_LABELS.get(ns, ns)
                click.echo("")
                click.echo(colored(f"-- {label} --", "yellow"))
            click.echo("")
            click.echo(colored(name, "blue") + f"  ({doc['type']})")
            for line in doc["description"].splitlines():
                click.echo(f"  {line}")
        return

    click.echo("")
    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        profile = require_active_profile(kv)
        prefix = _kv_prefix(profile)
        params_prefix = prefix + "params."
        keys = [
            k
            for k in kv.list_keys(prefix=params_prefix)
            if k[len(params_prefix):] in _ALLOWED_PARAMS
        ]
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
    Set a generation parameter.
    """
    typed_value = _parse_and_validate(name, value)
    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        profile = require_active_profile(kv)
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
        profile = require_active_profile(kv)
        prefix = _kv_prefix(profile)
        params_prefix = prefix + "params."
        keys = [
            k
            for k in kv.list_keys(prefix=params_prefix)
            if k[len(params_prefix):] in _ALLOWED_PARAMS
        ]
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
    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        profile = require_active_profile(kv)
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
        for line in doc["description"].splitlines():
            click.echo(f"  {line}")
