import click

from src.cli_obj import cli
from src.cli_routes.param import _ALLOWED_PARAMS
from src.data import get_pool
from src.utils.sql.kv_manager import KVManager
from src.utils.profile_utils import (
    get_active_profile,
    _kv_prefix,
    validate_profile_name,
)


def _mask_token(token_value: str) -> str:
    if not token_value:
        return "(empty)"
    return f"{token_value[:2]}...{token_value[-2:]}"


def _profile_verbose_lines(conn, kv, name: str) -> list[str]:
    """Return the indented metadata lines for one profile in verbose mode."""
    prefix = _kv_prefix(name)
    active_token = kv.get_value(prefix + "active_token")
    model_name = kv.get_value(prefix + "model")
    param_keys = kv.list_keys(prefix=prefix + "params.")

    lines = []

    if active_token:
        provider = active_token.get("provider", "")
        token_name = active_token.get("name", "")
        token_display = token_name if token_name else "(unnamed)"
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT token_value FROM tokens
                WHERE BINARY provider = BINARY %s
                  AND BINARY token_name = BINARY %s
                LIMIT 1
                """,
                (provider, token_name),
            )
            row = cursor.fetchone()
        if row:
            lines.append(
                f"  token : {provider} / {token_display} ({_mask_token(row[0])})"
            )
        else:
            lines.append(f"  token : {provider} / {token_display} (not found in DB)")
    else:
        lines.append("  token : (none)")

    lines.append(f"  model : {model_name or '(none)'}")

    visible_param_keys = [
        k for k in param_keys if k[len(prefix + "params.") :] in _ALLOWED_PARAMS
    ]
    if visible_param_keys:
        params_prefix = prefix + "params."
        parts = []
        for key in visible_param_keys:
            param_name = key[len(params_prefix) :]
            val = kv.get_value(key)
            parts.append(f"{param_name}={val}")
        lines.append(f"  params: {' '.join(parts)}")
    else:
        lines.append("  params: (none)")

    return lines


@cli.group()
def profile():
    """Manage named configuration profiles."""
    ...


@profile.command(name="new")
@click.argument("name", type=str)
def sub_cmd_new(name: str):
    """Create a new named profile."""
    err = validate_profile_name(name)
    if err:
        click.echo(f"Error: {err}")
        raise SystemExit(1)

    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM profiles WHERE name = %s LIMIT 1", (name,))
            if cursor.fetchone() is not None:
                click.echo(f"Error: Profile '{name}' already exists.")
                raise SystemExit(1)
            cursor.execute("INSERT INTO profiles (name) VALUES (%s)", (name,))
        conn.commit()
    click.echo(f"Profile '{name}' created.")


@profile.command(name="delete")
@click.argument("name", type=str)
def sub_cmd_delete(name: str):
    """Delete a profile and all its configuration."""
    if name.lower() == "default":
        click.echo("Error: 'default' is a reserved profile name.")
        raise SystemExit(1)

    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)

        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM profiles WHERE name = %s LIMIT 1", (name,))
            if cursor.fetchone() is None:
                click.echo(f"Error: Profile '{name}' does not exist.")
                raise SystemExit(1)

        active_profile = get_active_profile(kv)
        if active_profile == name:
            click.echo(f"Warning: '{name}' is the currently active profile.")
            if not click.confirm("Switch to 'default' and delete?", default=False):
                click.echo("Aborted.")
                return

        keys = kv.list_keys(prefix=f"profiles.{name}.")
        for key in keys:
            kv.delete_value(key)

        if active_profile == name:
            kv.set_value("active_profile", "default")

        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM profiles WHERE name = %s", (name,))
        conn.commit()
    click.echo(f"Profile '{name}' deleted.")


@profile.command(name="use")
@click.argument("name", type=str)
def sub_cmd_use(name: str):
    """Switch the active profile."""
    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        if name.lower() != "default":
            err = validate_profile_name(name)
            if err:
                click.echo(f"Error: {err}")
                raise SystemExit(1)
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM profiles WHERE name = %s LIMIT 1", (name,)
                )
                if cursor.fetchone() is None:
                    click.echo(f"Error: Profile '{name}' does not exist.")
                    raise SystemExit(1)
        kv.set_value("active_profile", name)
        conn.commit()
    click.echo(f"Switched to profile '{name}'.")


@profile.command(name="show")
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Show token, model, and params.",
)
def sub_cmd_show(verbose: bool):
    """Show the active profile."""
    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        active = get_active_profile(kv)

        marker = click.style("*", fg="cyan") + " "
        name_str = click.style(active, bold=True)
        click.echo(f"{marker}{name_str}")

        if verbose:
            for line in _profile_verbose_lines(conn, kv, active):
                click.echo(line)


@profile.command(name="list")
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Show token, model, and params for each profile.",
)
def sub_cmd_list(verbose: bool):
    """List all profiles."""
    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        active = get_active_profile(kv)

        with conn.cursor() as cursor:
            cursor.execute("SELECT name FROM profiles ORDER BY name")
            rows = cursor.fetchall()

        all_profiles = ["default"] + [r[0] for r in rows]

        for i, name in enumerate(all_profiles):
            if i > 0 and verbose:
                click.echo("")

            is_active = name == active
            marker = click.style("*", fg="cyan") if is_active else " "
            name_str = click.style(name, bold=is_active)
            click.echo(f"{marker} {name_str}")

            if verbose:
                for line in _profile_verbose_lines(conn, kv, name):
                    click.echo(line)


@profile.command(name="migrate")
@click.argument("name", type=str)
def sub_cmd_migrate(name: str):
    """Copy the current profile's config into a new named profile and switch to it."""
    err = validate_profile_name(name)
    if err:
        click.echo(f"Error: {err}")
        raise SystemExit(1)

    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)

        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM profiles WHERE name = %s LIMIT 1", (name,))
            if cursor.fetchone() is not None:
                click.echo(f"Error: Profile '{name}' already exists.")
                raise SystemExit(1)

        active_profile = get_active_profile(kv)
        dst_prefix = _kv_prefix(name)

        if active_profile == "default":
            src_keys = []
            for key in ("active_token", "model"):
                if kv.exists(key):
                    src_keys.append(key)
            src_keys += kv.list_keys(prefix="params.")
            for src_key in src_keys:
                val = kv.get_value(src_key)
                if val is not None:
                    kv.set_value(dst_prefix + src_key, val)
        else:
            src_prefix = _kv_prefix(active_profile)
            src_keys = kv.list_keys(prefix=src_prefix)
            for src_key in src_keys:
                val = kv.get_value(src_key)
                if val is not None:
                    kv.set_value(dst_prefix + src_key[len(src_prefix) :], val)

        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO profiles (name) VALUES (%s)", (name,))
        kv.set_value("active_profile", name)
        conn.commit()

    click.echo(
        f"Migrated '{active_profile}' configuration to profile '{name}'. Now active."
    )
