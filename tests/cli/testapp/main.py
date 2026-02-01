# tests/cli/testapp/main.py
"""Test application for CLI integration tests."""

import click
from cuneus import build_app, BaseExtension


class TestExtension(BaseExtension):
    pass


app, cli, lifespan = build_app(TestExtension)


@cli.command()
def custom():
    """A custom user command."""
    click.echo("custom command executed")


@app.get("/hello")
def hello():
    return {"message": "hello"}
