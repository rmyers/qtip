import click

from ..core.extensions import BaseExtension
from ..utils import import_from_string


class ServerExtension(BaseExtension):
    """Provides dev/prod/routes CLI commands."""

    def register_cli(self, cli_group: click.Group) -> None:
        settings = self.settings

        @cli_group.command()
        @click.option("--host", default="0.0.0.0", help="Bind host")
        @click.option("--port", default=8000, type=int, help="Bind port")
        def dev(host: str, port: int) -> None:
            """Run the application in development mode with reload."""
            import uvicorn

            uvicorn.run(
                settings.app_module,
                host=host,
                port=port,
                reload=True,
                log_config=None,
                server_header=False,
            )

        @cli_group.command()
        @click.option("--host", default="0.0.0.0", help="Bind host")
        @click.option("--port", default=8000, type=int, help="Bind port")
        @click.option("--workers", default=1, type=int, help="Number of workers")
        def prod(host: str, port: int, workers: int) -> None:
            """Run the application in production mode."""
            import uvicorn

            uvicorn.run(
                settings.app_module,
                host=host,
                port=port,
                workers=workers,
                log_config=None,
                server_header=False,
            )

        @cli_group.command()
        def routes() -> None:
            """List all registered routes."""
            app = import_from_string(settings.app_module)

            for route in app.routes:
                if hasattr(route, "methods"):  # pragma: no branch
                    methods = ",".join(route.methods - {"HEAD", "OPTIONS"})
                    click.echo(f"{methods:8} {route.path}")
