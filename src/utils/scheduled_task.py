"""
Registers/controls a Windows Scheduled Task that runs `slbp server run` at
user logon, via the `schtasks` CLI.

Support files (wrapper script + log) live in a single gitignored directory
at the project root, so their location is predictable regardless of where
`slbp` is invoked from.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

TASK_NAME = "SLBP Server"
SUPPORT_DIR = PROJECT_ROOT / ".slbp-task"
WRAPPER_SCRIPT = SUPPORT_DIR / "run_server.cmd"
HIDDEN_LAUNCHER = SUPPORT_DIR / "hidden_launch.vbs"
LOG_FILE = SUPPORT_DIR / "server.log"
TASK_XML = SUPPORT_DIR / "task_definition.xml"

# Give Docker Desktop / MySQL / Redis / Piston time to come up after logon
# before the preflight checks give up.
WAIT_FOR_DOCKER_SECONDS = 180


def _write_wrapper_script() -> None:
    """(Re)generate the .cmd file that the scheduled task actually runs.

    schtasks handles a single executable path far more reliably than a /TR
    string containing shell redirection, so the redirection to the log file
    lives in this wrapper instead of in the task definition itself.
    """
    SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    slbp_cmd = PROJECT_ROOT / "slbp.cmd"
    WRAPPER_SCRIPT.write_text(
        "@echo off\n"
        f'cd /d "{PROJECT_ROOT}"\n'
        f'echo. >> "{LOG_FILE}"\n'
        f'echo ==== %DATE% %TIME% : starting slbp server ==== >> "{LOG_FILE}"\n'
        f'"{slbp_cmd}" server run --wait-for-docker {WAIT_FOR_DOCKER_SECONDS} '
        f'>> "{LOG_FILE}" 2>&1\n'
        f'echo ==== %DATE% %TIME% : slbp server exited (code %ERRORLEVEL%) ==== '
        f'>> "{LOG_FILE}"\n'
    )


def _write_hidden_launcher() -> None:
    """
    Generate a VBScript that launches the wrapper .cmd with a fully hidden
    window.

    The task's <Hidden> setting only hides the *task* from the Task
    Scheduler UI — it has no effect on whether the launched process shows a
    window. wscript.exe is a GUI-subsystem host with no console of its own,
    and WshShell.Run's windowStyle=0 hides the *launched* process's window
    too, so routing the action through it is what actually suppresses the
    console flash. bWaitOnReturn=True keeps wscript.exe (and so the task)
    alive for the server's whole lifetime, so `schtasks /Query` status and
    `/End` (which kills the whole job-object process tree) keep working the
    same as when cmd.exe was the direct action.
    """
    HIDDEN_LAUNCHER.write_text(
        'Set WshShell = CreateObject("WScript.Shell")\n'
        f'WshShell.Run """{WRAPPER_SCRIPT}""", 0, True\n'
    )


def task_exists() -> bool:
    r = subprocess.run(
        ["schtasks", "/Query", "/TN", TASK_NAME],
        capture_output=True,
    )
    return r.returncode == 0


def _write_task_xml() -> None:
    """
    Build the Task Scheduler XML definition. schtasks' simple /Create flags
    (/SC, /TR, ...) can't express an action beyond a single command + args,
    so a hand-built XML definition (passed via /XML) is used to route the
    action through the hidden VBScript launcher (see _write_hidden_launcher).
    """
    username = os.environ.get("USERNAME", "")
    xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{username}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>false</StartWhenAvailable>
    <Hidden>true</Hidden>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>%SystemRoot%\\System32\\wscript.exe</Command>
      <Arguments>//B "{HIDDEN_LAUNCHER}"</Arguments>
    </Exec>
  </Actions>
</Task>
"""
    TASK_XML.write_text(xml, encoding="utf-16")


def create_or_update_task() -> None:
    """(Idempotently) register the task to run at user logon.

    Uses /F to overwrite any existing task of the same name, so calling this
    repeatedly (e.g. after moving the repo) just refreshes the definition.
    """
    SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    _write_wrapper_script()
    _write_hidden_launcher()
    _write_task_xml()
    r = subprocess.run(
        ["schtasks", "/Create", "/F", "/TN", TASK_NAME, "/XML", str(TASK_XML)],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(
            f"schtasks /Create failed: {r.stderr.strip() or r.stdout.strip()}"
        )


def start_task() -> None:
    r = subprocess.run(
        ["schtasks", "/Run", "/TN", TASK_NAME],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(
            f"schtasks /Run failed: {r.stderr.strip() or r.stdout.strip()}"
        )


def end_task() -> None:
    """Stop any currently running instance of the task, if one exists."""
    subprocess.run(
        ["schtasks", "/End", "/TN", TASK_NAME],
        capture_output=True,
        text=True,
    )


def delete_task() -> None:
    """Stop any running instance, then unregister the scheduled task."""
    end_task()
    r = subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(
            f"schtasks /Delete failed: {r.stderr.strip() or r.stdout.strip()}"
        )


def task_status() -> str | None:
    """
    Return the scheduled task's Status field (e.g. "Running", "Ready",
    "Disabled"), or None if the task isn't registered.
    """
    r = subprocess.run(
        ["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST", "/V"],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return None
    for line in r.stdout.splitlines():
        if line.startswith("Status:"):
            return line.split(":", 1)[1].strip()
    return None


def check_gateway(proxy_port: int, timeout: float = 2.0) -> tuple[bool, float | None]:
    """
    Probe a lightweight backend route through the gateway (exercises both the
    proxy and the Flask backend it forwards to). Returns (reachable, elapsed_ms).
    """
    start = time.monotonic()
    try:
        r = httpx.get(
            f"http://127.0.0.1:{proxy_port}/api/session-defaults", timeout=timeout
        )
        elapsed_ms = (time.monotonic() - start) * 1000
        return r.status_code == 200, elapsed_ms
    except httpx.HTTPError:
        return False, None
