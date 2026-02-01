from cuneus import build_app


app, cli, lifespan = build_app()

__all__ = ["app", "cli", "lifespan"]
