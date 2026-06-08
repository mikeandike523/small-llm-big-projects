import click

from src.cli_obj import cli
from src.utils.param_registry import ALLOWED_PARAMS as _ALLOWED_PARAMS
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
    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)

        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM profiles WHERE name = %s LIMIT 1", (name,))
            if cursor.fetchone() is None:
                click.echo(f"Error: Profile '{name}' does not exist.")
                raise SystemExit(1)

        active_profile = get_active_profile(kv)
        is_active = active_profile == name
        if is_active:
            click.echo(
                click.style(
                    f"Warning: '{name}' is the currently selected default profile.",
                    fg="yellow",
                )
            )
            if not click.confirm(
                "Delete it? (No default profile will be selected afterwards.)",
                default=False,
            ):
                click.echo("Aborted.")
                return

        keys = kv.list_keys(prefix=f"profiles.{name}.")
        for key in keys:
            kv.delete_value(key)

        if is_active:
            kv.delete_value("active_profile")

        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM profiles WHERE name = %s", (name,))
        conn.commit()
    click.echo(f"Profile '{name}' deleted.")


@profile.command(name="use")
@click.argument("name", type=str)
def sub_cmd_use(name: str):
    """Set the default profile."""
    err = validate_profile_name(name)
    if err:
        click.echo(f"Error: {err}")
        raise SystemExit(1)

    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM profiles WHERE name = %s LIMIT 1", (name,))
            if cursor.fetchone() is None:
                click.echo(f"Error: Profile '{name}' does not exist.")
                raise SystemExit(1)
        kv.set_value("active_profile", name)
        conn.commit()
    click.echo(f"Default profile set to '{name}'.")


@profile.command(name="show")
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Show token, model, and params.",
)
def sub_cmd_show(verbose: bool):
    """Show the default profile."""
    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        active = get_active_profile(kv)

        if active is None:
            click.echo("No default profile selected.")
            return

        marker = click.style("*", fg="cyan") + " "
        name_str = click.style(active, bold=True)
        click.echo(f"{marker}{name_str}")

        if verbose:
            for line in _profile_verbose_lines(conn, kv, active):
                click.echo(line)


@profile.command(name="copy-to")
@click.argument("name", type=str)
def sub_cmd_copy_to(name: str):
    """Copy the default profile's config to a new named profile."""
    err = validate_profile_name(name)
    if err:
        click.echo(f"Error: {err}")
        raise SystemExit(1)

    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)

        active_profile = get_active_profile(kv)
        if active_profile is None:
            click.echo("Error: No default profile selected.")
            raise SystemExit(1)

        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM profiles WHERE name = %s LIMIT 1", (name,))
            already_exists = cursor.fetchone() is not None

        if already_exists:
            if not click.confirm(f"Overwrite profile '{name}'?", default=False):
                click.echo("Aborted.")
                return
            for key in kv.list_keys(prefix=_kv_prefix(name)):
                kv.delete_value(key)

        src_prefix = _kv_prefix(active_profile)
        dst_prefix = _kv_prefix(name)
        for src_key in kv.list_keys(prefix=src_prefix):
            val = kv.get_value(src_key)
            if val is not None:
                kv.set_value(dst_prefix + src_key[len(src_prefix):], val)

        if not already_exists:
            with conn.cursor() as cursor:
                cursor.execute("INSERT INTO profiles (name) VALUES (%s)", (name,))
        conn.commit()

    click.echo(f"Copied profile '{active_profile}' to '{name}'.")


def _rename_profile(conn, kv, old_name: str, new_name: str) -> None:
    src_prefix = _kv_prefix(old_name)
    dst_prefix = _kv_prefix(new_name)
    src_keys = kv.list_keys(prefix=src_prefix)
    for src_key in src_keys:
        val = kv.get_value(src_key)
        if val is not None:
            kv.set_value(dst_prefix + src_key[len(src_prefix):], val)
    for src_key in src_keys:
        kv.delete_value(src_key)
    if get_active_profile(kv) == old_name:
        kv.set_value("active_profile", new_name)
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM profiles WHERE name = %s", (old_name,))
        cursor.execute("INSERT INTO profiles (name) VALUES (%s)", (new_name,))


@profile.command(name="rename")
@click.argument("old_name", type=str)
@click.argument("new_name", type=str)
def sub_cmd_rename(old_name: str, new_name: str):
    """Rename a profile."""
    err = validate_profile_name(new_name)
    if err:
        click.echo(f"Error: {err}")
        raise SystemExit(1)

    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM profiles WHERE name = %s LIMIT 1", (old_name,))
            if cursor.fetchone() is None:
                click.echo(f"Error: Profile '{old_name}' does not exist.")
                raise SystemExit(1)
            cursor.execute("SELECT 1 FROM profiles WHERE name = %s LIMIT 1", (new_name,))
            if cursor.fetchone() is not None:
                click.echo(f"Error: Profile '{new_name}' already exists.")
                raise SystemExit(1)
        _rename_profile(conn, kv, old_name, new_name)
        conn.commit()
    click.echo(f"Renamed profile '{old_name}' to '{new_name}'.")


@profile.command(name="rename-to")
@click.argument("new_name", type=str)
def sub_cmd_rename_to(new_name: str):
    """Rename the default profile."""
    err = validate_profile_name(new_name)
    if err:
        click.echo(f"Error: {err}")
        raise SystemExit(1)

    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        active_profile = get_active_profile(kv)
        if active_profile is None:
            click.echo("Error: No default profile selected.")
            raise SystemExit(1)
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM profiles WHERE name = %s LIMIT 1", (new_name,))
            if cursor.fetchone() is not None:
                click.echo(f"Error: Profile '{new_name}' already exists.")
                raise SystemExit(1)
        _rename_profile(conn, kv, active_profile, new_name)
        conn.commit()
    click.echo(f"Renamed profile '{active_profile}' to '{new_name}'.")


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

        all_profiles = [r[0] for r in rows]

        if not all_profiles:
            click.echo("No profiles. Use 'slbp profile new <name>' to create one.")
            return

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
