"""
Launches/talks to the SLBP Electron desktop app instead of a plain webbrowser.open().

Mirrors the .slbp-server.json pattern in server_state.py: the Electron app writes
its own control-server port to .slbp-app-server.json at the repo root on startup,
and removes it on clean quit. This module never trusts OS process listing -- a
short HTTP health-check against the recorded port is the only "is it running"
signal, since a stale/orphaned port file just fails the health-check cleanly.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import click
import httpx

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_APP_STATE_FILE = _PROJECT_ROOT / ".slbp-app-server.json"
_DESKTOP_DIR = _PROJECT_ROOT / "desktop"
_PRODUCT_NAME = "SLBP"
_ICON_PATH = _DESKTOP_DIR / "assets" / "icons" / "icon.ico"
_INSTALL_STATE_FILE = _PROJECT_ROOT / ".slbp-desktop-install.json"

_HEALTH_TIMEOUT = 1.0
_POLL_INTERVAL_SECONDS = 0.3
_MAX_WAIT_SECONDS = 30.0


def _read_app_state() -> dict | None:
    if not _APP_STATE_FILE.exists():
        return None
    try:
        import json

        return json.loads(_APP_STATE_FILE.read_text())
    except (OSError, ValueError):
        return None


def _health_check(port: int) -> bool:
    try:
        response = httpx.get(
            f"http://127.0.0.1:{port}/health", timeout=_HEALTH_TIMEOUT
        )
        return response.status_code == 200
    except httpx.HTTPError:
        return False


def _platform_arch() -> tuple[str, str]:
    system = platform.system()
    platform_map = {"Windows": "win32", "Darwin": "darwin", "Linux": "linux"}
    forge_platform = platform_map.get(system)
    if forge_platform is None:
        raise click.ClickException(f"Unsupported OS for the SLBP desktop app: {system}")

    machine = platform.machine().lower()
    arch_map = {
        "amd64": "x64",
        "x86_64": "x64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }
    forge_arch = arch_map.get(machine)
    if forge_arch is None:
        raise click.ClickException(f"Unsupported CPU architecture for the SLBP desktop app: {machine}")

    return forge_platform, forge_arch


def _executable_path() -> Path:
    forge_platform, forge_arch = _platform_arch()
    out_dir = _DESKTOP_DIR / "out" / f"{_PRODUCT_NAME}-{forge_platform}-{forge_arch}"
    if forge_platform == "win32":
        return out_dir / f"{_PRODUCT_NAME}.exe"
    if forge_platform == "darwin":
        return out_dir / f"{_PRODUCT_NAME}.app" / "Contents" / "MacOS" / _PRODUCT_NAME
    return out_dir / _PRODUCT_NAME


def _rebuild_command_hint() -> str:
    if not (_DESKTOP_DIR / "node_modules").exists():
        return "cd desktop && pnpm install && pnpm run package"
    return "pnpm --dir desktop run package"


def _latest_source_mtime() -> float:
    latest = 0.0
    for pattern in ("src/**/*", "assets/**/*", "forge.config.ts", "package.json"):
        for path in _DESKTOP_DIR.glob(pattern):
            if path.is_file():
                latest = max(latest, path.stat().st_mtime)
    return latest


def _ensure_build_is_fresh(exe_path: Path) -> None:
    if not exe_path.exists():
        raise click.ClickException(
            "The SLBP desktop app has not been built yet.\n"
            f"Build it first: {_rebuild_command_hint()}"
        )
    if _latest_source_mtime() > exe_path.stat().st_mtime:
        raise click.ClickException(
            "The SLBP desktop app build is older than its source.\n"
            f"Rebuild it: {_rebuild_command_hint()}"
        )


def install_start_menu_shortcut() -> Path:
    """
    (Idempotently) create/overwrite a Start Menu shortcut for the desktop
    app, launching it the same way `_spawn_app` does. Windows only — there's
    no reliable, non-hacky way to also pin it to the taskbar (Windows 11
    blocks programmatic taskbar pinning); the user can do that themselves
    with a right-click on the Start Menu entry.
    """
    if sys.platform != "win32":
        raise click.ClickException("Start Menu shortcuts are only supported on Windows.")

    exe_path = _executable_path()
    _ensure_build_is_fresh(exe_path)

    start_menu_programs = (
        Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    )
    shortcut_path = start_menu_programs / f"{_PRODUCT_NAME}.lnk"

    # WScript.Shell's CreateShortcut is the standard, dependency-free way to
    # write a .lnk file on Windows (no need for pywin32).
    vbs = (
        'Set oWS = CreateObject("WScript.Shell")\n'
        f'Set oLink = oWS.CreateShortcut("{shortcut_path}")\n'
        f'oLink.TargetPath = "{exe_path}"\n'
        f'oLink.Arguments = "--repo-root " & Chr(34) & "{_PROJECT_ROOT}" & Chr(34)\n'
        f'oLink.WorkingDirectory = "{exe_path.parent}"\n'
        f'oLink.IconLocation = "{exe_path}, 0"\n'
        'oLink.Description = "SLBP"\n'
        "oLink.Save()\n"
    )

    fd, vbs_path = tempfile.mkstemp(suffix=".vbs")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(vbs)
        r = subprocess.run(
            ["cscript.exe", "//nologo", "//B", vbs_path],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            raise RuntimeError(
                f"Failed to create Start Menu shortcut: {r.stderr.strip() or r.stdout.strip()}"
            )
    finally:
        Path(vbs_path).unlink(missing_ok=True)

    return shortcut_path


def _icon_sha256() -> str | None:
    if not _ICON_PATH.exists():
        return None
    return hashlib.sha256(_ICON_PATH.read_bytes()).hexdigest()


def icon_changed_since_last_install() -> bool:
    """
    Compare the packaged Windows icon's hash against the one recorded by the
    previous `slbp desktop install` run, then persist the current hash for
    next time.

    Returns True only when a previous hash was recorded AND it differs —
    i.e. never on the first install, and never when nothing changed. Windows
    caches shortcut/taskbar icons per-file and doesn't reliably notice an
    in-place icon change, so this is what drives the "restart Explorer?"
    prompt in the CLI layer.
    """
    current = _icon_sha256()
    if current is None:
        return False

    previous = None
    if _INSTALL_STATE_FILE.exists():
        try:
            previous = json.loads(_INSTALL_STATE_FILE.read_text()).get("icon_sha256")
        except (OSError, ValueError):
            previous = None

    _INSTALL_STATE_FILE.write_text(json.dumps({"icon_sha256": current}))

    return previous is not None and previous != current


def restart_explorer() -> None:
    """Kill and relaunch explorer.exe, forcing Windows to refresh its icon cache."""
    subprocess.run(["taskkill", "/f", "/im", "explorer.exe"], capture_output=True)
    subprocess.Popen(["explorer.exe"])


def _spawn_app(exe_path: Path) -> None:
    args = [str(exe_path), "--repo-root", str(_PROJECT_ROOT)]
    if sys.platform == "win32":
        subprocess.Popen(
            args,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
            close_fds=True,
        )
    else:
        subprocess.Popen(args, start_new_session=True, close_fds=True)


def _wait_for_running_app() -> int:
    """Poll every 300ms for the control server to come up, echoing progress."""
    waited = 0.0
    click.echo("[slbp] Waiting for the SLBP app to start", nl=False)
    while waited < _MAX_WAIT_SECONDS:
        state = _read_app_state()
        if state and _health_check(state.get("port", -1)):
            click.echo("  ready.")
            return state["port"]
        click.echo(".", nl=False)
        time.sleep(_POLL_INTERVAL_SECONDS)
        waited += _POLL_INTERVAL_SECONDS
    click.echo()
    raise click.ClickException(
        f"The SLBP app did not become ready within {_MAX_WAIT_SECONDS:.0f}s."
    )


def _ensure_app_running() -> int:
    """Return a healthy control-server port, launching the app if needed."""
    state = _read_app_state()
    if state and _health_check(state.get("port", -1)):
        return state["port"]

    exe_path = _executable_path()
    _ensure_build_is_fresh(exe_path)
    _spawn_app(exe_path)
    return _wait_for_running_app()


def _send_open(port: int, payload: dict) -> None:
    try:
        response = httpx.post(f"http://127.0.0.1:{port}/open", json=payload, timeout=5)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise click.ClickException(f"Failed to open in the SLBP app: {exc}")


def open_session(session_id: str, proxy_port: int) -> None:
    port = _ensure_app_running()
    _send_open(
        port,
        {"sessionId": session_id, "proxyOrigin": f"http://localhost:{proxy_port}"},
    )


def open_dashboard(proxy_port: int) -> None:
    port = _ensure_app_running()
    _send_open(
        port,
        {"dashboard": True, "proxyOrigin": f"http://localhost:{proxy_port}"},
    )
