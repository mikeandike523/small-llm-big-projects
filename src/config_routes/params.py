from __future__ import annotations

from flask import jsonify, request

from src.ui_connector.app import app
from src.data import get_pool
from src.utils.sql.kv_manager import KVManager
from src.utils.profile_utils import get_active_profile, _kv_prefix
from src.utils.param_registry import ALLOWED_PARAMS, parse_param_value as _parse_and_validate

_NAMESPACES = ("model", "watchdog.model", "summarizer.model", "patchrewriter.model")
_SYSTEM_KEYS = ("system.return_value_max_chars", "system.blank_response_retries")
_MODEL_EXTRA = ("model.irat",)


@app.route("/api/params", methods=["GET"])
def api_params_get():
    """Return all set params grouped by namespace."""
    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        profile = get_active_profile(kv)
        if not profile:
            return jsonify({"error": "No active profile"}), 400
        prefix = _kv_prefix(profile)
        params_prefix = prefix + "params."
        all_keys = kv.list_keys(prefix=params_prefix)
        result: dict[str, dict] = {ns: {} for ns in _NAMESPACES}
        result["system"] = {}
        for k in all_keys:
            name = k[len(params_prefix):]
            if name not in ALLOWED_PARAMS:
                continue
            val = kv.get_value(k)
            # Route to the correct namespace bucket
            for ns in _NAMESPACES:
                if name.startswith(ns + "."):
                    suffix = name[len(ns) + 1:]
                    result[ns][suffix] = val
                    break
            else:
                result["system"][name] = val
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
        profile = get_active_profile(kv)
        if not profile:
            return jsonify({"error": "No active profile"}), 400
        prefix = _kv_prefix(profile)
        kv.set_value(f"{prefix}params.{name}", typed)
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
        profile = get_active_profile(kv)
        if not profile:
            return jsonify({"error": "No active profile"}), 400
        prefix = _kv_prefix(profile)
        key = f"{prefix}params.{name}"
        if kv.exists(key):
            kv.delete_value(key)
            conn.commit()
    return jsonify({"ok": True, "name": name})
