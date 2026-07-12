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
for _stream in (_sys.stdout, _sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

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

# Routes with separate subroutes
importlib.import_module("src.cli_routes.token.subroutes")


from src.cli_obj import cli

if __name__ == "__main__":
    cli()
