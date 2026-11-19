from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request(url: str, *, method: str = "GET", headers: dict[str, str] | None = None, body: bytes | None = None):
    request = urllib.request.Request(url, method=method, headers=headers or {}, data=body)
    try:
        return urllib.request.urlopen(request, timeout=5)
    except urllib.error.HTTPError as exc:
        return exc


def test_artifact_server_uses_metadata_etags_and_revalidates(tmp_path: Path):
    public_port = _free_port()
    control_port = _free_port()
    state_file = tmp_path / "artifacts.json"
    (tmp_path / "index.html").write_text("<h1>artifact</h1>", encoding="utf-8")
    (tmp_path / "large.bin").write_bytes(b"x" * 101)
    listing_dir = tmp_path / "listing"
    listing_dir.mkdir()
    (listing_dir / "one.txt").write_text("one", encoding="utf-8")
    (listing_dir / "two.txt").write_text("two", encoding="utf-8")
    env = {
        **os.environ,
        "ARTIFACT_PORT": str(public_port),
        "ARTIFACT_CONTROL_PORT": str(control_port),
        "ARTIFACT_SECRET": "test-secret",
        "ARTIFACT_ORIGIN": "https://artifact.example.com",
        "ARTIFACT_STATE_FILE": str(state_file),
        "ARTIFACT_MAX_FILE_BYTES": "100",
        "ARTIFACT_MAX_DIRECTORY_ENTRIES": "1",
        "ARTIFACT_SERVE_TIMEOUT_MS": "5000",
    }
    process = subprocess.Popen(
        ["node", str(PROJECT_ROOT / "proxy-server" / "artifact-server.js")],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        health_url = f"http://127.0.0.1:{control_port}/health"
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                if _request(health_url, headers={"Authorization": "Bearer test-secret"}).status == 200:
                    break
            except (urllib.error.URLError, ConnectionError):
                time.sleep(0.05)
        else:
            raise AssertionError("artifact control server did not become ready")

        control_headers = {"Authorization": "Bearer test-secret", "Content-Type": "application/json"}
        create = _request(
            health_url.replace("/health", "/artifacts"),
            method="POST",
            headers=control_headers,
            body=json.dumps({"directory": str(tmp_path), "session_id": "test-session"}).encode(),
        )
        artifact = json.loads(create.read())
        artifact_host = f"{artifact['id']}.artifact.example.com"
        file_url = f"http://127.0.0.1:{public_port}/index.html"

        first = _request(file_url, headers={"Host": artifact_host})
        etag = first.headers.get("ETag")
        assert first.status == 200
        assert etag and etag.startswith('W/"')
        assert first.headers.get("Cache-Control") == "no-cache"
        assert first.read() == b"<h1>artifact</h1>"

        cached = _request(
            file_url,
            headers={"Host": artifact_host, "If-None-Match": etag},
        )
        assert cached.code == 304

        oversized = _request(
            file_url.replace("index.html", "large.bin"),
            headers={"Host": artifact_host},
        )
        assert oversized.code == 413

        oversized_listing = _request(
            file_url.replace("index.html", "listing/"),
            headers={"Host": artifact_host},
        )
        assert oversized_listing.code == 413

        stopped = _request(
            health_url.replace("/health", f"/artifacts/{artifact['id']}"),
            method="DELETE",
            headers={"Authorization": "Bearer test-secret"},
        )
        assert stopped.status == 200
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
