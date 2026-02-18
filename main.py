import importlib

importlib.import_module("src.cli_routes.token")
importlib.import_module("src.cli_routes.endpoint")
importlib.import_module("src.cli_routes.model")
importlib.import_module("src.cli_routes.chat")

from src.cli_obj import cli

if __name__ == "__main__":
    cli()