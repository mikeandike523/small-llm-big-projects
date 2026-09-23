from __future__ import annotations

import os

from src.utils.session_model import Session


def skills_info_payload(session: Session, registry: list[dict]) -> dict:
    if not session.load_custom_skills_tools:
        return {"enabled": False, "count": 0, "path": None, "files": []}
    labels = sorted(
        f"{entry['name']} ({entry['id']})"
        + (" [autoload]" if entry["autoload"] else "")
        for entry in registry
        if entry["source"] == "custom"
    )
    return {
        "enabled": True,
        "count": len(labels),
        "path": os.path.join(session.initial_cwd, "skills").replace("\\", "/"),
        "files": labels,
    }


def tools_info_payload(tool_defs: list[dict], plugins: list[dict]) -> dict:
    total = len(tool_defs)
    custom_count = sum(plugin["count"] for plugin in plugins)
    return {
        "totalCount": total,
        "builtinCount": total - custom_count,
        "builtinPath": "src/tools/",
        "names": [definition["function"]["name"] for definition in tool_defs],
        "customPlugins": plugins or None,
    }
