from __future__ import annotations

import json
from typing import Any

from flask import jsonify, request

from src.data import get_pool
from src.ui_connector.app import app
from src.utils.param_registry import ALLOWED_PARAMS as _ALLOWED_PARAMS
from src.utils.profile_utils import (
    _kv_prefix,
    get_active_profile,
    validate_profile_name,
)
from src.utils.sql.kv_manager import KVManager


_PARAM_SPECS: dict[str, dict[str, Any]] = {
    "model.temperature": {
        "value_type": "float",
        "min": 0.0,
        "max": 2.0,
        "description": "Controls generation randomness.",
    },
    "model.top_p": {
        "value_type": "float",
        "min": 0.0,
        "max": 1.0,
        "description": "Nucleus sampling threshold.",
    },
    "model.top_k": {
        "value_type": "integer",
        "min": 1,
        "description": "Limits token candidates to the top K choices.",
    },
    "model.max_tokens": {
        "value_type": "integer",
        "min": 1,
        "description": "Maximum generated tokens for the main model response.",
    },
    "model.watchdog_max_tokens": {
        "value_type": "integer",
        "min": 1,
        "description": "Maximum generated tokens for watchdog LLM calls.",
    },
    "model.title_summary_max_tokens": {
        "value_type": "integer",
        "min": 1,
        "description": "Maximum generated tokens for task title summaries.",
    },
    "model.request_extra_params": {
        "value_type": "object",
        "description": "JSON object merged into every model request payload.",
    },
    "model.irat": {
        "value_type": "boolean",
        "description": "Treat interim response content as thinking in new sessions.",
    },
    "system.return_value_max_chars": {
        "value_type": "integer",
        "min": 1,
        "description": "Maximum inline tool return characters before stubbing.",
    },
}


def _param_specs_payload() -> list[dict[str, Any]]:
    return [
        {"name": name, **_PARAM_SPECS.get(name, {"value_type": "string"})}
        for name in sorted(_ALLOWED_PARAMS)
    ]


def _parse_param_value(name: str, raw_value: Any) -> Any:
    if name not in _ALLOWED_PARAMS:
        raise ValueError(f"Unknown param '{name}'.")

    spec = _PARAM_SPECS.get(name, {"value_type": "string"})
    value_type = spec["value_type"]
    if value_type == "boolean":
        if isinstance(raw_value, bool):
            return raw_value
        if isinstance(raw_value, str) and raw_value.lower() in ("true", "false"):
            return raw_value.lower() == "true"
        raise ValueError(f"{name} must be true or false.")

    if value_type == "object":
        value = raw_value
        if isinstance(raw_value, str):
            try:
                value = json.loads(raw_value)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{name} must be valid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{name} must be a JSON object.")
        return value

    if value_type == "integer":
        try:
            value = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be an integer.") from exc
    elif value_type == "float":
        try:
            value = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a number.") from exc
    else:
        return str(raw_value)

    min_value = spec.get("min")
    max_value = spec.get("max")
    if min_value is not None and value < min_value:
        raise ValueError(f"{name} must be >= {min_value}.")
    if max_value is not None and value > max_value:
        raise ValueError(f"{name} must be <= {max_value}.")
    return value


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
                if param_name in _ALLOWED_PARAMS:
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


@app.route("/api/profiles/<profile_name>/params/<path:param_name>", methods=["PUT"])
def api_profiles_set_param(profile_name: str, param_name: str):
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
