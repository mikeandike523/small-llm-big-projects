import click

from src.data import get_pool
from src.cli_obj import cli
from src.utils.sql.kv_manager import KVManager

@cli.group()
def model():
    ...

@model.command(name="use")
@click.argument("model_name", type=str, required=False)
def sub_cmd_use(model_name):
    """
    Sets the active model by name
    """

    pool=get_pool()
    with pool.get_connection() as conn:
        KVManager(conn).set_value("model",model_name)
        conn.commit()
    click.echo(f"Set current model to: {model_name or '(not set)'}")

@model.command(name="show")
def sub_cmd_show():
    """
    Show the current model name
    """
    pool=get_pool()
    with pool.get_connection() as conn:
        model_name = KVManager(conn).get_value("model")
        if not model_name:
            model_name = None
        click.echo(f"Current model name: {model_name or '(not set)'}")


        