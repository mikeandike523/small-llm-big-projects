from __future__ import annotations

from flask import jsonify, request

from src.ui_connector.app import app
from src.data import get_pool
from src.utils.sql.kv_manager import KVManager
from src.utils.profile_utils import get_active_profile, _kv_prefix
from src.utils.param_registry import (
    ALLOWED_PARAMS,
    GLOBAL_PARAMS,
    REGISTRY,
    parse_param_value as _parse_and_validate,
    param_storage_key as _param_storage_key,
)

_NAMESPACES = ("model", "watchdog.model", "summarizer.model", "patchrewriter.model")
_SYSTEM_KEYS = (
    "system.return_value_max_chars",
    "system.blank_response_retries",
    "system.strict_dirty",
    "system.create_file_auto_eol",
    "system.enable_patch_rewriter",
)
_MODEL_EXTRA = ("model.irat",)


def _get_all_params(kv, profile) -> dict[str, dict]:
    """Return all set params grouped by namespace, reading from both profile and global scope."""
    prefix = _kv_prefix(profile)
    profile_params_prefix = prefix + "params."
    global_params_prefix = "params."

    result: dict[str, dict] = {ns: {} for ns in _NAMESPACES}
    result["system"] = {}

    # Collect keys from both scopes; prefer profile-scoped value when both exist.
    profile_keys = {}
    for k in kv.list_keys(prefix=profile_params_prefix):
        name = k[len(profile_params_prefix):]
        if name in ALLOWED_PARAMS and name not in GLOBAL_PARAMS:
            profile_keys[name] = k

    global_keys = {}
    for k in kv.list_keys(prefix=global_params_prefix):
        name = k[len(global_params_prefix):]
        if name in GLOBAL_PARAMS:
            global_keys[name] = k

    # Merge: profile-scoped names override for profile-scoped params; global names fill in.
    for name, k in {**global_keys, **profile_keys}.items():
        val = kv.get_value(k)
        for ns in _NAMESPACES:
            if name.startswith(ns + "."):
                suffix = name[len(ns) + 1:]
                result[ns][suffix] = val
                break
        else:
            result["system"][name] = val

    return result


@app.route("/api/params", methods=["GET"])
def api_params_get():
    """Return all set params grouped by namespace."""
    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        profile = get_active_profile(kv)
        if not profile:
            return jsonify({"error": "No active profile"}), 400
        result = _get_all_params(kv, profile)
    return jsonify(result)


@app.route("/api/params/set", methods=["POST"])
def api_params_set():
    """Set a single param. Body: {name, value} where value is always a string."""
    data = request.get_json(force=True) or {}
    name = data.get("name", "")
    raw_value = data.get("value", "")
    if not name:
        return jsonify({"error": "name required"}), 400
    if name not in ALLOWED_PARAMS:
        return jsonify({"error": f"Unknown param '{name}'"}), 400
    try:
        typed = _parse_and_validate(name, str(raw_value))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        spec = REGISTRY[name]
        if spec.scope == "global":
            key = _param_storage_key(name)  # params.<name>
        else:
            profile = get_active_profile(kv)
            if not profile:
                return jsonify({"error": "No active profile"}), 400
            prefix = _kv_prefix(profile)
            key = _param_storage_key(name, profile_prefix=prefix)
        kv.set_value(key, typed)
        conn.commit()
    return jsonify({"ok": True, "name": name, "value": typed})


@app.route("/api/params/unset", methods=["POST"])
def api_params_unset():
    """Unset (delete) a param. Body: {name}."""
    data = request.get_json(force=True) or {}
    name = data.get("name", "")
    if not name:
        return jsonify({"error": "name required"}), 400

    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        spec = REGISTRY[name]
        if spec.scope == "global":
            key = _param_storage_key(name)
        else:
            profile = get_active_profile(kv)
            if not profile:
                return jsonify({"error": "No active profile"}), 400
            prefix = _kv_prefix(profile)
            key = _param_storage_key(name, profile_prefix=prefix)
        if kv.exists(key):
            kv.delete_value(key)
            conn.commit()
    return jsonify({"ok": True, "name": name})