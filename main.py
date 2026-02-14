import importlib

importlib.import_module("src.cli_routes.token")

from src.cli_obj import cli

if __name__ == "__main__":
    cli()