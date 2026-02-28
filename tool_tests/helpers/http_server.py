from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass


@dataclass
class MicroServer:
    port: int
    pid: int
    base_url: str
    _process: subprocess.Popen


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.1)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except (ConnectionRefusedError, socket.timeout, OSError):
            return False


def start_server() -> MicroServer:
    port = find_free_port()
    script = os.path.join(os.path.dirname(__file__), "_server_script.py")
    proc = subprocess.Popen(
        [sys.executable, script, str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    deadline = time.time() + 3.0
    while time.time() < deadline:
        if _port_open(port):
            break
        time.sleep(0.05)
    else:
        proc.terminate()
        raise RuntimeError(f"Micro HTTP server did not start within 3s on port {port}")

    return MicroServer(
        port=port,
        pid=proc.pid,
        base_url=f"http://127.0.0.1:{port}",
        _process=proc,
    )


def stop_server(server: MicroServer) -> None:
    try:
        server._process.terminate()
        server._process.wait(timeout=3)
    except Exception:
        try:
            server._process.kill()
            server._process.wait(timeout=2)
        except Exception:
            pass
