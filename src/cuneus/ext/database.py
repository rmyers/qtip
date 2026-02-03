# cuneus/ext/database.py
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import click
import svcs
from fastapi import FastAPI
from pydantic import Field, SecretStr, computed_field
from pydantic_settings import SettingsConfigDict
from structlog.stdlib import get_logger
from sqlalchemy import URL, make_url, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..core.extensions import BaseExtension, HasCLI
from ..core.settings import CuneusBaseSettings, DEFAULT_TOOL_NAME

logger = get_logger(__name__)


class DatabaseSettings(CuneusBaseSettings):
    """Database configuration."""

    model_config = SettingsConfigDict(
        env_prefix="DATABASE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        pyproject_toml_depth=2,
        pyproject_toml_table_header=("tool", DEFAULT_TOOL_NAME, "database"),
    )

    # Option 1: Full URL (takes precedence if set)
    url: str | None = None

    # Option 2: Individual parts
    driver: str = "postgresql+asyncpg"
    host: str = "localhost"
    port: int = 5432
    name: str = "app"
    username: str | None = None
    password: SecretStr | None = None

    # Pool settings
    pool_size: int = 5
    pool_max_overflow: int = 10
    pool_recycle: int = 3600
    echo: bool = False

    # Alembic
    alembic_config: Path = Path("alembic.ini")

    @computed_field
    @property
    def url_parsed(self) -> URL:
        """Get SQLAlchemy URL, either from url string or constructed from parts."""
        if self.url:
            return make_url(self.url)

        needs_opts = "sqlite" not in self.driver
        password_value = self.password.get_secret_value() if self.password else None
        password = password_value if needs_opts else None

        return URL.create(
            drivername=self.driver,
            username=self.username if needs_opts else None,
            password=password,
            host=self.host if needs_opts else None,
            port=self.port if needs_opts else None,
            database=self.name,
        )

    @computed_field
    @property
    def url_redacted(self) -> str:
        """URL safe for logging (password hidden)."""
        return self.url_parsed.render_as_string(hide_password=True)


class DatabaseExtension(BaseExtension, HasCLI):
    """
    Database extension providing AsyncSession via svcs.

    Registers:
        - AsyncEngine: The SQLAlchemy async engine
        - async_sessionmaker: Factory for creating sessions
        - AsyncSession: Request-scoped session (via factory)

    CLI Commands:
        - db upgrade [revision]: Run migrations
        - db downgrade [revision]: Rollback migrations
        - db revision -m "message": Create new migration
        - db current: Show current revision
        - db history: Show migration history
        - db check: Check database connectivity

    Configuration (env or pyproject.toml [tool.cuneus.database]):
        DATABASE_URL: Connection string
        DATABASE_POOL_SIZE: Connection pool size (default: 5)
        DATABASE_POOL_MAX_OVERFLOW: Max overflow connections (default: 10)
        DATABASE_POOL_RECYCLE: Connection recycle time in seconds (default: 3600)
        DATABASE_ECHO: Echo SQL statements (default: false)
        DATABASE_ALEMBIC_CONFIG: Path to alembic.ini (default: alembic.ini)
    """

    _session_factory: async_sessionmaker[AsyncSession]
    _engine: AsyncEngine

    def __init__(self, settings: DatabaseSettings | None = None):
        self.settings = settings or DatabaseSettings()

    @asynccontextmanager
    async def register(
        self, registry: svcs.Registry, app: FastAPI
    ) -> AsyncIterator[dict[str, Any]]:
        self._engine = create_async_engine(
            self.settings.url_parsed,
            # pool_size=self.settings.pool_size,
            # max_overflow=self.settings.pool_max_overflow,
            pool_recycle=self.settings.pool_recycle,
            echo=self.settings.echo,
        )

        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        registry.register_value(AsyncEngine, self._engine, ping=self._check)
        registry.register_value(async_sessionmaker, self._session_factory)

        @asynccontextmanager
        async def session_factory() -> AsyncIterator[AsyncSession]:
            async with self._session_factory() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

        registry.register_factory(AsyncSession, session_factory)

        logger.info("Database started", extra={"url": self.settings.url_redacted})

        try:
            yield {
                "db_engine": self._engine,
                "db_session_factory": self._session_factory,
            }
        finally:
            await self._engine.dispose()
            logger.info("Database shutdown")

    async def _check(self):
        engine = create_async_engine(self.settings.url_parsed)
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        finally:
            await engine.dispose()

    def register_cli(self, cli_group: click.Group) -> None:
        settings = self.settings

        @cli_group.group()
        def db():
            """Database management commands."""
            pass

        @db.command()
        @click.argument("revision", default="head")
        def upgrade(revision: str):
            """Upgrade database to revision (default: head)."""
            _run_alembic_cmd("upgrade", settings.alembic_config, revision=revision)

        @db.command()
        @click.argument("revision", default="-1")
        def downgrade(revision: str):
            """Downgrade database to revision (default: -1)."""
            _run_alembic_cmd("downgrade", settings.alembic_config, revision=revision)

        @db.command()
        @click.option("-m", "--message", required=True, help="Migration message")
        @click.option("--autogenerate/--no-autogenerate", default=True)
        def revision(message: str, autogenerate: bool):
            """Create a new migration revision."""
            _run_alembic_cmd(
                "revision",
                settings.alembic_config,
                message=message,
                autogenerate=autogenerate,
            )

        @db.command()
        def current():
            """Show current database revision."""
            _run_alembic_cmd("current", settings.alembic_config)

        @db.command()
        def history():
            """Show migration history."""
            _run_alembic_cmd("history", settings.alembic_config)

        @db.command()
        @click.argument("template", default="async")
        def init():
            """
            Create a new alembic setup by default this will use the async template
            """

        @db.command()
        @click.pass_context
        def check(ctx: click.Context):
            """Check database connectivity."""
            import asyncio

            async def _check():
                engine = create_async_engine(settings.url_parsed)
                try:
                    async with engine.connect() as conn:
                        await conn.execute(text("SELECT 1"))
                    click.echo("✓ Database connection OK")
                except Exception as e:
                    print(e)
                    click.echo(f"✗ Database connection failed: {e}", err=True)
                    ctx.exit(1)
                finally:
                    await engine.dispose()

            asyncio.run(_check())


def _run_alembic_cmd(
    cmd: str,
    config_path: Path,
    revision: str | None = None,
    message: str | None = None,
    autogenerate: bool = False,
) -> None:
    """Run an alembic command."""
    from alembic import command
    from alembic.config import Config

    if not config_path.exists():
        raise click.ClickException(f"Alembic config not found: {config_path}")

    cfg = Config(str(config_path))

    match cmd:
        case "upgrade":
            command.upgrade(cfg, revision or "head")
        case "downgrade":
            command.downgrade(cfg, revision or "-1")
        case "revision":
            command.revision(cfg, message=message, autogenerate=autogenerate)
        case "current":
            command.current(cfg)
        case "history":
            command.history(cfg)
        case _:
            raise click.ClickException(f"Unknown command: {cmd}")


def _redact_url(url: str) -> str:
    """Redact password from database URL for logging."""
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(url)
    if parsed.password:
        netloc = f"{parsed.username}:***@{parsed.hostname}"
        if parsed.port:
            netloc += f":{parsed.port}"
        parsed = parsed._replace(netloc=netloc)
    return urlunparse(parsed)
