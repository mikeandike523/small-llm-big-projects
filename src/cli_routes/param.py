import json

import click
from termcolor import colored

from src.data import get_pool
from src.cli_obj import cli
from src.utils.sql.kv_manager import KVManager

_ALLOWED_PARAMS = {
    "model.temperature",
    "model.top_p",
    "model.top_k",
    "model.max_tokens",
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
        if name == "model.top_k":
            value = int(raw_value)
            if value <= 0:
                raise click.BadParameter("model.top_k must be > 0", param_hint="value")
            return value
        elif name == "model.max_tokens":
            value = int(raw_value)
            if value <= 0:
                raise click.BadParameter("model.max_tokens must be > 0", param_hint="value")
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
        int_params = {"model.top_k", "model.max_tokens", "system.return_value_max_chars", "system.assistant_strip_truncation_chars"}
        type_hint = "integer" if name in int_params else "float"
        raise click.BadParameter(f"value for '{name}' must be a {type_hint}", param_hint="value")


@cli.group()
def param():
    ...

@param.command("list")
def sub_cmd_list():
    click.echo('')
    pool = get_pool()
    with pool.get_connection() as conn:
        SQL="""
SELECT * FROM `kv_store` where `key` like "params.%"
"""
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(SQL)
            results = cursor.fetchall()
            if not results:
                click.echo("No params set.")
            for i, result in enumerate(results):
                is_last = i == len(results) - 1
                key=result['key']
                value_str=result["value"]
                try:
                    value=json.loads(value_str)
                    print(f"""
{colored(key,'blue')}:

{json.dumps(value, indent=2)}
""".strip()+("\n\n" if not is_last else ""))

                except json.JSONDecodeError as e:
                    click.echo(f"""
{colored(key,'blue')}:

[Invalid JSON]

{value_str}
""".strip()+("\n\n" if not is_last else ""))

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
        KVManager(conn).set_value(f"params.{name}", typed_value)
        conn.commit()
    click.echo(f"Set params.{name} = {typed_value}")


@param.command(name="show")
def sub_cmd_show():
    """
    Show all currently set generation parameters.
    """
    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        keys = kv.list_keys(prefix="params.")
        if not keys:
            click.echo("No params set.")
            return
        for key in keys:
            param_name = key[len("params."):]
            val = kv.get_value(key)
            click.echo(f"{param_name} = {val}")


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
        if not kv.exists(f"params.{name}"):
            click.echo(f"params.{name} is not set.")
            return
        kv.delete_value(f"params.{name}")
        conn.commit()
    click.echo(f"Unset params.{name}")


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
