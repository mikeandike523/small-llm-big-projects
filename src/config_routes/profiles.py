from __future__ import annotations

from typing import Any

from flask import jsonify, request

from src.data import get_pool
from src.ui_connector.app import app
from src.utils.param_registry import ALLOWED_PARAMS as _ALLOWED_PARAMS
from src.utils.param_registry import GLOBAL_PARAMS as _GLOBAL_PARAMS
from src.utils.param_registry import REGISTRY as _REGISTRY
from src.utils.param_registry import parse_param_value as _parse_param_value
from src.utils.profile_utils import (
    _kv_prefix,
    get_active_profile,
    validate_profile_name,
)
from src.utils.sql.kv_manager import KVManager


def _param_specs_payload() -> list[dict[str, Any]]:
    return [_REGISTRY[name].to_api_dict() for name in sorted(_REGISTRY)]


def _profile_exists(cursor, name: str) -> bool:
    cursor.execute("SELECT 1 FROM profiles WHERE name = %s LIMIT 1", (name,))
    return cursor.fetchone() is not None


def _require_profile(cursor, name: str):
    if not _profile_exists(cursor, name):
        return jsonify({"error": f"Profile '{name}' does not exist."}), 404
    return None


def _token_payload(row) -> dict[str, Any]:
    return {
        "id": row[0],
        "provider": row[1],
        "name": row[2] or "",
        "label": f"{row[1]} / {row[2]}" if row[2] else f"{row[1]} / (no name)",
    }


@app.route("/api/profiles/config", methods=["GET"])
def api_profiles_config():
    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        default_profile = get_active_profile(kv)
        with conn.cursor() as cursor:
            cursor.execute("SELECT name FROM profiles ORDER BY name")
            profile_rows = cursor.fetchall()
            cursor.execute(
                "SELECT id, provider, token_name FROM tokens ORDER BY provider, token_name"
            )
            token_rows = cursor.fetchall()

        names = [row[0] for row in profile_rows]
        profiles = []
        for name in names:
            prefix = _kv_prefix(name)
            params_prefix = prefix + "params."
            params = {}
            for key in kv.list_keys(prefix=params_prefix):
                param_name = key[len(params_prefix) :]
                if param_name in _ALLOWED_PARAMS and param_name not in _GLOBAL_PARAMS:
                    params[param_name] = kv.get_value(key)
            profiles.append(
                {
                    "name": name,
                    "is_default": name == default_profile,
                    "model": kv.get_value(prefix + "model", "") or "",
                    "active_token": kv.get_value(prefix + "active_token"),
                    "params": params,
                }
            )

    return jsonify(
        {
            "default_profile": default_profile,
            "profiles": profiles,
            "tokens": [_token_payload(row) for row in token_rows],
            "param_specs": _param_specs_payload(),
        }
    )


@app.route("/api/profiles", methods=["POST"])
def api_profiles_create():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    err = validate_profile_name(name)
    if err:
        return jsonify({"error": err}), 400

    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor() as cursor:
            if _profile_exists(cursor, name):
                return jsonify({"error": f"Profile '{name}' already exists."}), 409
            cursor.execute("INSERT INTO profiles (name) VALUES (%s)", (name,))
        conn.commit()
    return jsonify({"ok": True})


@app.route("/api/profiles/default", methods=["PATCH"])
def api_profiles_set_default():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        with conn.cursor() as cursor:
            missing = _require_profile(cursor, name)
            if missing:
                return missing
        kv.set_value("active_profile", name)
        conn.commit()
    return jsonify({"ok": True})


@app.route("/api/profiles/<profile_name>", methods=["PATCH"])
def api_profiles_patch(profile_name: str):
    data = request.get_json(force=True, silent=True) or {}
    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        with conn.cursor() as cursor:
            missing = _require_profile(cursor, profile_name)
            if missing:
                return missing

            prefix = _kv_prefix(profile_name)
            if "model" in data:
                model = (data.get("model") or "").strip()
                if model:
                    kv.set_value(prefix + "model", model)
                else:
                    kv.delete_value(prefix + "model")

            if "token_id" in data:
                token_id = data.get("token_id")
                if token_id in (None, ""):
                    kv.delete_value(prefix + "active_token")
                else:
                    cursor.execute(
                        "SELECT provider, token_name FROM tokens WHERE id=%s",
                        (token_id,),
                    )
                    row = cursor.fetchone()
                    if not row:
                        return jsonify({"error": "Token not found."}), 404
                    kv.set_value(
                        prefix + "active_token",
                        {"provider": row[0], "name": row[1] or ""},
                    )
        conn.commit()
    return jsonify({"ok": True})


@app.route("/api/profiles/<profile_name>/rename", methods=["POST"])
def api_profiles_rename(profile_name: str):
    data = request.get_json(force=True, silent=True) or {}
    new_name = (data.get("new_name") or "").strip()
    err = validate_profile_name(new_name)
    if err:
        return jsonify({"error": err}), 400

    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        with conn.cursor() as cursor:
            missing = _require_profile(cursor, profile_name)
            if missing:
                return missing
            if _profile_exists(cursor, new_name):
                return jsonify({"error": f"Profile '{new_name}' already exists."}), 409

        src_prefix = _kv_prefix(profile_name)
        dst_prefix = _kv_prefix(new_name)
        src_keys = kv.list_keys(prefix=src_prefix)
        for src_key in src_keys:
            val = kv.get_value(src_key)
            if val is not None:
                kv.set_value(dst_prefix + src_key[len(src_prefix):], val)
        for src_key in src_keys:
            kv.delete_value(src_key)
        if get_active_profile(kv) == profile_name:
            kv.set_value("active_profile", new_name)
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM profiles WHERE name = %s", (profile_name,))
            cursor.execute("INSERT INTO profiles (name) VALUES (%s)", (new_name,))
        conn.commit()
    return jsonify({"ok": True})


@app.route("/api/profiles/<profile_name>/copy-to", methods=["POST"])
def api_profiles_copy_to(profile_name: str):
    data = request.get_json(force=True, silent=True) or {}
    new_name = (data.get("new_name") or "").strip()
    err = validate_profile_name(new_name)
    if err:
        return jsonify({"error": err}), 400

    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        with conn.cursor() as cursor:
            missing = _require_profile(cursor, profile_name)
            if missing:
                return missing
            if _profile_exists(cursor, new_name):
                return jsonify({"error": f"Profile '{new_name}' already exists."}), 409

        src_prefix = _kv_prefix(profile_name)
        dst_prefix = _kv_prefix(new_name)
        for src_key in kv.list_keys(prefix=src_prefix):
            val = kv.get_value(src_key)
            if val is not None:
                kv.set_value(dst_prefix + src_key[len(src_prefix):], val)
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO profiles (name) VALUES (%s)", (new_name,))
        conn.commit()
    return jsonify({"ok": True})


@app.route("/api/profiles/<profile_name>/params/<path:param_name>", methods=["PUT"])
def api_profiles_set_param(profile_name: str, param_name: str):
    if param_name not in _ALLOWED_PARAMS:
        return jsonify({"error": f"Unknown param '{param_name}'."}), 400
    if param_name in _GLOBAL_PARAMS:
        return jsonify({
            "error": f"Param '{param_name}' is global-scoped; use /api/params/set instead."
        }), 400

    data = request.get_json(force=True, silent=True) or {}
    try:
        value = _parse_param_value(param_name, data.get("value"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        with conn.cursor() as cursor:
            missing = _require_profile(cursor, profile_name)
            if missing:
                return missing
        kv.set_value(_kv_prefix(profile_name) + "params." + param_name, value)
        conn.commit()
    return jsonify({"ok": True, "value": value})


@app.route("/api/profiles/<profile_name>/params/<path:param_name>", methods=["DELETE"])
def api_profiles_unset_param(profile_name: str, param_name: str):
    if param_name not in _ALLOWED_PARAMS:
        return jsonify({"error": f"Unknown param '{param_name}'."}), 400
    if param_name in _GLOBAL_PARAMS:
        return jsonify({
            "error": f"Param '{param_name}' is global-scoped; use /api/params/unset instead."
        }), 400

    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        with conn.cursor() as cursor:
            missing = _require_profile(cursor, profile_name)
            if missing:
                return missing
        kv.delete_value(_kv_prefix(profile_name) + "params." + param_name)
        conn.commit()
    return jsonify({"ok": True})


@app.route("/api/profiles/<profile_name>", methods=["DELETE"])
def api_profiles_delete(profile_name: str):
    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        with conn.cursor() as cursor:
            missing = _require_profile(cursor, profile_name)
            if missing:
                return missing
            for key in kv.list_keys(prefix=f"profiles.{profile_name}."):
                kv.delete_value(key)
            cursor.execute("DELETE FROM profiles WHERE name = %s", (profile_name,))
        if get_active_profile(kv) == profile_name:
            kv.delete_value("active_profile")
        conn.commit()
    return jsonify({"ok": True})
