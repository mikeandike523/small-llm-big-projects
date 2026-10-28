from click.testing import CliRunner

from src.cli_obj import cli
from src.cli_routes import session as session_route
from src.utils import app_launcher


class _Connection:
    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        return False


class _Pool:
    def get_connection(self):
        return _Connection()


class _Response:
    status_code = 200
    is_error = False
    text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return {"session_id": "session-123"}


def _prepare_session_creation(monkeypatch):
    monkeypatch.setattr(session_route, "get_pool", lambda: _Pool())
    monkeypatch.setattr(
        session_route, "require_active_profile", lambda _kv: "default-profile"
    )
    monkeypatch.setattr(
        session_route, "get_param_value", lambda *_args, **_kwargs: False
    )
    monkeypatch.setattr(
        session_route,
        "read_state",
        lambda: {"flask_port": 5100, "proxy_port": 5200},
    )
    monkeypatch.setattr(
        session_route.httpx, "post", lambda *_args, **_kwargs: _Response()
    )


def test_session_new_browser_uses_default_web_browser(monkeypatch):
    _prepare_session_creation(monkeypatch)
    desktop_calls = []
    browser_calls = []
    monkeypatch.setattr(
        session_route,
        "open_session",
        lambda *args: desktop_calls.append(args),
    )
    monkeypatch.setattr(
        session_route,
        "open_session_in_browser",
        lambda *args: browser_calls.append(args),
    )

    result = CliRunner().invoke(
        cli, ["session", "new", "--browser", "--no-load-startup-tool-calls"]
    )

    assert result.exit_code == 0
    assert browser_calls == [("session-123", 5200)]
    assert desktop_calls == []


def test_session_new_defaults_to_desktop_app(monkeypatch):
    _prepare_session_creation(monkeypatch)
    desktop_calls = []
    browser_calls = []
    monkeypatch.setattr(
        session_route,
        "open_session",
        lambda *args: desktop_calls.append(args),
    )
    monkeypatch.setattr(
        session_route,
        "open_session_in_browser",
        lambda *args: browser_calls.append(args),
    )

    result = CliRunner().invoke(cli, ["session", "new", "--no-load-startup-tool-calls"])

    assert result.exit_code == 0
    assert desktop_calls == [("session-123", 5200)]
    assert browser_calls == []


def test_session_new_help_documents_browser_flag():
    result = CliRunner().invoke(cli, ["session", "new", "--help"])

    assert result.exit_code == 0
    assert "--browser" in result.output
    assert "default web browser" in result.output
    assert "instead of the desktop app" in result.output


def test_browser_launcher_opens_session_url(monkeypatch):
    opened_urls = []
    monkeypatch.setattr(
        app_launcher.webbrowser, "open", lambda url: opened_urls.append(url)
    )

    app_launcher.open_session_in_browser("session with spaces", 5200)

    assert opened_urls == [
        "http://localhost:5200/session?sessionId=session+with+spaces"
    ]
