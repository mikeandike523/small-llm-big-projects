import importlib
import os as _os

# Scrub SSL_CERT_FILE if it points to a missing file — httpx raises
# FileNotFoundError before any network call if the path doesn't exist.
_ssl_cert = _os.environ.get("SSL_CERT_FILE")
if _ssl_cert and not _os.path.exists(_ssl_cert):
    _os.environ.pop("SSL_CERT_FILE", None)

importlib.import_module("src.cli_routes.endpoint")
importlib.import_module("src.cli_routes.model")
importlib.import_module("src.cli_routes.param")
importlib.import_module("src.cli_routes.chat")
importlib.import_module("src.cli_routes.session")
importlib.import_module("src.cli_routes.server")
importlib.import_module("src.cli_routes.service_token")
importlib.import_module("src.cli_routes.dashboard")
importlib.import_module("src.cli_routes.profile")

# Routes with separate subroutes
importlib.import_module("src.cli_routes.token.subroutes")


from src.cli_obj import cli

if __name__ == "__main__":
    cli()
