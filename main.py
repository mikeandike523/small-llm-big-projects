import importlib

importlib.import_module("src.cli_routes.token")
importlib.import_module("src.cli_routes.endpoint")
importlib.import_module("src.cli_routes.model")
importlib.import_module("src.cli_routes.param")
importlib.import_module("src.cli_routes.chat")
importlib.import_module("src.cli_routes.ui")

from src.cli_obj import cli

if __name__ == "__main__":
    cli()