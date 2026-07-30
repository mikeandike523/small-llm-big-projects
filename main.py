import importlib
import os as _os
import sys as _sys

# Scrub SSL_CERT_FILE if it points to a missing file — httpx raises
# FileNotFoundError before any network call if the path doesn't exist.
_ssl_cert = _os.environ.get("SSL_CERT_FILE")
if _ssl_cert and not _os.path.exists(_ssl_cert):
    _os.environ.pop("SSL_CERT_FILE", None)

# On Windows, stdout/stderr default to the legacy cp1252 codepage when not
# attached to a real console (piped, or redirected to a log file by a
# scheduled task) — click.echo() of the ✅/❌ etc. used throughout the CLI
# then crashes with UnicodeEncodeError instead of printing.
#
# The same "not a real console" case (e.g. Git Bash/MinTTY, which presents
# stdout as a pipe rather than a Win32 console handle) also makes Python
# fall back to full block buffering instead of line buffering. Output then
# sits in an internal buffer until it fills or the interpreter shuts down,
# so it can visibly land after the shell has already reclaimed the terminal
# and drawn its next prompt — forcing line_buffering=True here flushes each
# click.echo() line as it's written instead.
for _stream in (_sys.stdout, _sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

importlib.import_module("src.cli_routes.endpoint")
importlib.import_module("src.cli_routes.model")
importlib.import_module("src.cli_routes.param")
importlib.import_module("src.cli_routes.chat")
importlib.import_module("src.cli_routes.session")
importlib.import_module("src.cli_routes.server")
importlib.import_module("src.cli_routes.service_token")
importlib.import_module("src.cli_routes.dashboard")
importlib.import_module("src.cli_routes.profile")
importlib.import_module("src.cli_routes.desktop")

importlib.import_module("src.cli_routes.phpmyadmin")

# Routes with separate subroutes
importlib.import_module("src.cli_routes.token.subroutes")


from src.cli_obj import cli

if __name__ == "__main__":
    cli()
