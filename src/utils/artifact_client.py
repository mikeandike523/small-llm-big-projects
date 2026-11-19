from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx


def _config() -> tuple[str, str]:
    port = os.environ.get("ARTIFACT_CONTROL_PORT")
    secret = os.environ.get("ARTIFACT_SECRET")
    if not port or not secret:
        raise RuntimeError("The artifact server is unavailable; start `slbp server run` first.")
    return f"http://127.0.0.1:{port}", secret


def _request(method: str, path: str, **kwargs: Any) -> dict | list:
    base, secret = _config()
    try:
        response = httpx.request(
            method,
            f"{base}{path}",
            headers={"Authorization": f"Bearer {secret}"},
            timeout=10,
            **kwargs,
        )
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Could not contact the artifact server: {exc}") from exc
    try:
        payload = response.json()
    except ValueError:
        payload = {"error": response.text}
    if response.status_code >= 400:
        raise RuntimeError(payload.get("error", f"artifact server returned HTTP {response.status_code}"))
    return payload


def create_artifact(directory: str, session_id: str) -> dict:
    return _request("POST", "/artifacts", json={"directory": directory, "session_id": session_id})  # type: ignore[return-value]


def list_artifacts() -> list[dict]:
    return _request("GET", "/artifacts")  # type: ignore[return-value]


def stop_artifact(artifact_id: str) -> dict:
    return _request("DELETE", f"/artifacts/{artifact_id}")  # type: ignore[return-value]


def artifact_url(artifact_id: str) -> str:
    origin = os.environ.get("ARTIFACT_ORIGIN", "http://artifact.localhost").strip().rstrip("/")
    if "://" not in origin:
        origin = f"http://{origin}"
    parsed = urlsplit(origin)
    hostname = parsed.hostname or "artifact.localhost"
    host = f"{artifact_id}.{hostname}"
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, "", "", "")) + "/"
