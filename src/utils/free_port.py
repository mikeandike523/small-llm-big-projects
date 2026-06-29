"""Utility for finding a free TCP port on the host."""

from __future__ import annotations

import socket
from collections.abc import Iterable

# Preferred ports for the gateway proxy. These sit in the upper, IANA-registered
# range and are not commonly claimed by other servers or dev tooling (avoiding
# the usual 3000/4200/5000/5173/8000/8080/9000 crowd). Trying these first means a
# restarted server usually lands on the same gateway port, so an already-open
# browser tab can reconnect without a new URL. This is a convenience only today;
# it lays groundwork for persistent (DB-backed) sessions later.
PREFERRED_GATEWAY_PORTS: tuple[int, ...] = (
    49737,
    49813,
    49901,
    50047,
    50123,
)


def _port_is_free(port: int) -> bool:
    """Return True if ``port`` can currently be bound on 127.0.0.1."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def find_free_port() -> int:
    """Bind a socket to port 0, let the OS assign a free port, return it.

    The socket is immediately closed after reading the port, so there is a
    brief TOCTOU window. In practice this is fine for local development use.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def find_preferred_port(preferred: Iterable[int] = PREFERRED_GATEWAY_PORTS) -> int:
    """Return the first free port from ``preferred``, falling back to a random one.

    Each candidate is checked in order; the first one that can be bound is
    returned. If none are available (all in use), an OS-assigned random free
    port is returned via :func:`find_free_port`.
    """
    for port in preferred:
        if _port_is_free(port):
            return port
    return find_free_port()
