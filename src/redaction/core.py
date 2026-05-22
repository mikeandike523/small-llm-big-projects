from __future__ import annotations

from src.redaction.types import RedactionPlugin


class RedactionEngine:
    """Selects the best-matching plugin for a file and delegates redaction to it.

    Usage:
        engine = RedactionEngine([DotenvPlugin(), GeneralPlugin()])
        safe = engine.redact(path, content)
    """

    def __init__(self, plugins: list[RedactionPlugin] | None = None) -> None:
        self._plugins: list[RedactionPlugin] = list(plugins or [])

    def register(self, plugin: RedactionPlugin) -> None:
        self._plugins.append(plugin)

    def redact(self, path: str | None, content: str) -> str:
        """Return redacted content, or the original string if no plugin matches."""
        best_plugin: RedactionPlugin | None = None
        best_score = 0.0

        for plugin in self._plugins:
            s = plugin.score(path, content)
            if s > best_score:
                best_score = s
                best_plugin = plugin

        if best_plugin is None:
            return content

        return best_plugin.redact(path, content)


# ---------------------------------------------------------------------------
# Module-level default engine — used by the tool execution pipeline
# ---------------------------------------------------------------------------

from src.redaction.plugins.redaction_plugin_dotenv import DotenvPlugin  # noqa: E402
from src.redaction.plugins.general_plugin import GeneralPlugin  # noqa: E402

_engine = RedactionEngine([DotenvPlugin(), GeneralPlugin()])


def redact(path: str | None, content: str) -> str:
    """Redact content through the default engine. Returns content unchanged if no plugin matches."""
    return _engine.redact(path, content)
