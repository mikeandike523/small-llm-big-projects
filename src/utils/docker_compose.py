"""
Helpers for running docker compose commands and discovering host-mapped ports.

Tries `docker compose` (plugin mode, modern) first, then falls back to
`docker-compose` (standalone legacy). Raises RuntimeError if neither is found.
"""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

# Path to the server/ directory containing docker-compose.yml, computed once
# using __file__ so it is correct regardless of the caller's cwd.
_COMPOSE_DIR = Path(__file__).resolve().parent.parent.parent / "server"


@lru_cache(maxsize=1)
def _find_docker_compose() -> list[str]:
    """Return the command prefix for docker compose (e.g. ['docker', 'compose']).

    Tries the modern plugin form first, then the legacy standalone binary.
    Raises RuntimeError if neither is available.
    """
    candidates = [
        ["docker", "compose"],
        ["docker-compose"],
    ]
    for candidate in candidates:
        try:
            result = subprocess.run(
                candidate + ["version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return candidate
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    raise RuntimeError(
        "Neither 'docker compose' nor 'docker-compose' is available. "
        "Install Docker Desktop (includes the compose plugin) or the "
        "standalone docker-compose binary before running this application."
    )


def run_docker_compose(
    args: list[str],
    cwd: Path | str | None = None,
    **subprocess_kwargs,
) -> subprocess.CompletedProcess:
    """Run a docker compose command.

    Args:
        args: Arguments after the 'docker compose' prefix (e.g. ['ps']).
        cwd:  Working directory; defaults to the server/ directory next to
              this file so the correct docker-compose.yml is used.
        **subprocess_kwargs: Forwarded to subprocess.run().

    Returns:
        subprocess.CompletedProcess
    """
    cmd = _find_docker_compose() + args
    effective_cwd = Path(cwd) if cwd is not None else _COMPOSE_DIR
    return subprocess.run(cmd, cwd=effective_cwd, **subprocess_kwargs)


def get_service_port(service: str, container_port: int, cwd: Path | str | None = None) -> int:
    """Return the host port mapped to container_port for the given service.

    Uses `docker compose port <service> <container_port>` to discover the
    actual host port assigned by Docker (works whether the mapping was set
    explicitly or via port-0 / random assignment).

    Args:
        service:        Docker Compose service name (e.g. 'mysql').
        container_port: The port inside the container (e.g. 3306).
        cwd:            Directory containing docker-compose.yml; defaults to
                        the server/ directory next to this file.

    Returns:
        int host port

    Raises:
        RuntimeError: if docker compose is unavailable or the command fails.
        ValueError:   if the command output cannot be parsed.
    """
    result = run_docker_compose(
        ["port", service, str(container_port)],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"docker compose port {service} {container_port} failed "
            f"(exit {result.returncode}):\n{result.stderr.strip()}"
        )
    output = result.stdout.strip()
    if not output:
        raise RuntimeError(
            f"docker compose port {service} {container_port} returned empty output. "
            f"Is the '{service}' container running?"
        )
    # Output is "0.0.0.0:PORT" or ":::PORT"
    _, port_str = output.rsplit(":", 1)
    try:
        return int(port_str)
    except ValueError as exc:
        raise ValueError(
            f"Could not parse port from docker compose output: {output!r}"
        ) from exc
