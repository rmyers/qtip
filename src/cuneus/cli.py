"""Cuneus CLI entry point."""

from typing import Any, cast

import click

from .core.settings import Settings, ensure_project_in_path
from .utils import import_from_string


def get_user_cli(config: Settings | None = None) -> click.Group | None:
    """Load CLI from config."""
    config = config or Settings()
    try:
        return cast(click.Group, import_from_string(config.cli_module))
    except (ImportError, AttributeError) as e:
        click.echo(
            f"Warning: Could not load CLI from {config.cli_module}: {e}", err=True
        )
        return None


class CuneusCLI(click.Group):
    """Delegates to the app's CLI from config."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._user_cli: click.Group | None = None
        self._user_cli_loaded = False

    @property
    def user_cli(self) -> click.Group | None:
        if not self._user_cli_loaded:
            self._user_cli = get_user_cli()
            self._user_cli_loaded = True
        return self._user_cli

    def list_commands(self, ctx: click.Context) -> list[str]:
        if self.user_cli:
            return self.user_cli.list_commands(ctx)
        return []

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        if self.user_cli:
            return self.user_cli.get_command(ctx, cmd_name)
        return None


ensure_project_in_path()
main = CuneusCLI(help="Cuneus CLI - FastAPI application framework")


if __name__ == "__main__":
    main()
