"""Utility for finding a free TCP port on the host."""

from __future__ import annotations

import socket


def find_free_port() -> int:
    """Bind a socket to port 0, let the OS assign a free port, return it.

    The socket is immediately closed after reading the port, so there is a
    brief TOCTOU window. In practice this is fine for local development use.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
