from __future__ import annotations

from flask import jsonify, request

from src.ui_connector.app import app
from src.data import get_pool
from src.utils.sql.kv_manager import KVManager
from src.utils.profile_utils import get_active_profile, _kv_prefix


def _mask(value: str) -> str:
    if not value or len(value) <= 4:
        return "****"
    return f"{value[:2]}****{value[-2:]}"


def _maybe_add_known_provider(cursor, provider: str, endpoint: str) -> None:
    cursor.execute(
        "SELECT 1 FROM known_providers WHERE BINARY provider_key = BINARY %s LIMIT 1",
        (provider,),
    )
    if cursor.fetchone() is None:
        cursor.execute(
            "INSERT INTO known_providers (provider_key, display_name, default_endpoint_url)"
            " VALUES (%s, %s, %s)",
            (provider, provider, endpoint),
        )


@app.route("/api/tokens", methods=["GET"])
def api_tokens_list():
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, provider, token_name, endpoint_url, token_value FROM tokens ORDER BY provider, token_name"
            )
            rows = cursor.fetchall()
    tokens = [
        {
            "id": row[0],
            "provider": row[1],
            "name": row[2] or "",
            "endpoint_url": row[3] or "",
            "masked_value": _mask(row[4] or ""),
        }
        for row in rows
    ]
    return jsonify({"tokens": tokens})


@app.route("/api/tokens/active", methods=["GET"])
def api_tokens_active():
    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        profile = get_active_profile(kv)
        active_token = kv.get_value(_kv_prefix(profile) + "active_token") if profile else None
    if not active_token:
        return jsonify(None)
    return jsonify(
        {
            "provider": active_token.get("provider", ""),
            "name": active_token.get("name", ""),
            "profile": profile,
        }
    )


@app.route("/api/tokens", methods=["POST"])
def api_tokens_add():
    data = request.get_json(force=True, silent=True) or {}
    provider = (data.get("provider") or "").strip()
    name = (data.get("name") or "").strip()
    endpoint = (data.get("endpoint") or "").strip() or None
    value = (data.get("value") or "").strip()
    if not provider:
        return jsonify({"error": "provider is required"}), 400
    if not value:
        return jsonify({"error": "value is required"}), 400
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM tokens WHERE BINARY provider=BINARY %s"
                " AND BINARY token_name=BINARY %s LIMIT 1",
                (provider, name),
            )
            if cursor.fetchone():
                return (
                    jsonify(
                        {
                            "error": f"Token ({provider!r}, {name!r}) already exists."
                            " Use the Rotate button to update its value."
                        }
                    ),
                    409,
                )
            cursor.execute(
                "INSERT INTO tokens (provider, endpoint_url, token_name, token_value)"
                " VALUES (%s,%s,%s,%s)",
                (provider, endpoint, name, value),
            )
            if endpoint:
                _maybe_add_known_provider(cursor, provider, endpoint)
        conn.commit()
    return jsonify({"ok": True})


@app.route("/api/tokens/<int:token_id>", methods=["PATCH"])
def api_tokens_patch(token_id: int):
    data = request.get_json(force=True, silent=True) or {}
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT provider, token_name, endpoint_url FROM tokens WHERE id=%s",
                (token_id,),
            )
            row = cursor.fetchone()
        if not row:
            return jsonify({"error": "Token not found"}), 404
        old_provider, old_name, old_endpoint = row

        new_provider = (data.get("provider") or old_provider).strip()
        new_name = (data["name"] if "name" in data else old_name or "").strip()
        endpoint_in_payload = "endpoint_url" in data
        new_endpoint = (
            ((data.get("endpoint_url") or "").strip() or None)
            if endpoint_in_payload
            else old_endpoint
        )

        if (new_provider, new_name) != (old_provider, old_name):
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM tokens WHERE BINARY provider=BINARY %s"
                    " AND BINARY token_name=BINARY %s AND id!=%s LIMIT 1",
                    (new_provider, new_name, token_id),
                )
                if cursor.fetchone():
                    return (
                        jsonify(
                            {"error": "That provider+name combination is already taken"}
                        ),
                        409,
                    )

        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE tokens SET provider=%s, token_name=%s, endpoint_url=%s WHERE id=%s",
                (new_provider, new_name, new_endpoint, token_id),
            )
            if endpoint_in_payload and new_endpoint and new_endpoint != old_endpoint:
                _maybe_add_known_provider(cursor, new_provider, new_endpoint)
        conn.commit()
    return jsonify({"ok": True})


@app.route("/api/tokens/<int:token_id>/rotate", methods=["POST"])
def api_tokens_rotate(token_id: int):
    data = request.get_json(force=True, silent=True) or {}
    value = (data.get("value") or "").strip()
    if not value:
        return jsonify({"error": "value is required"}), 400
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE tokens SET token_value=%s WHERE id=%s",
                (value, token_id),
            )
            if cursor.rowcount == 0:
                return jsonify({"error": "Token not found"}), 404
        conn.commit()
    return jsonify({"ok": True})


@app.route("/api/tokens/<int:token_id>/value", methods=["GET"])
def api_tokens_get_value(token_id: int):
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT provider, token_name, endpoint_url, token_value FROM tokens WHERE id=%s",
                (token_id,),
            )
            row = cursor.fetchone()
    if not row:
        return jsonify({"error": "Token not found"}), 404
    return jsonify(
        {
            "provider": row[0],
            "name": row[1] or "",
            "endpoint": row[2] or "",
            "value": row[3] or "",
        }
    )


@app.route("/api/tokens/<int:token_id>", methods=["DELETE"])
def api_tokens_delete(token_id: int):
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM tokens WHERE id=%s LIMIT 1", (token_id,))
            if not cursor.fetchone():
                return jsonify({"error": "Token not found"}), 404
            cursor.execute("DELETE FROM tokens WHERE id=%s", (token_id,))
        conn.commit()
    return jsonify({"ok": True})
