# tests/ext/test_database.py
from __future__ import annotations

from typing import Any

import pytest
from click.testing import CliRunner
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.testclient import TestClient
from svcs import Registry
from svcs.fastapi import DepContainer

from cuneus import build_app, BaseExtension
from cuneus.ext.database import DatabaseExtension, DatabaseSettings


def sqlite_settings() -> DatabaseSettings:
    """In-memory SQLite for testing."""
    return DatabaseSettings(driver="sqlite+aiosqlite", name=":memory:")


class DatabaseConsumerExtension(BaseExtension):
    """Extension that uses the database."""

    async def startup(self, registry: Registry, app: FastAPI) -> dict[str, Any]:
        @app.get("/db-test")
        async def db_test(container: DepContainer):
            session = await container.aget(AsyncSession)
            result = await session.execute(text("SELECT 1"))
            return {"value": result.scalar()}

        @app.get("/db-write")
        async def db_write(container: DepContainer):
            session = await container.aget(AsyncSession)
            await session.execute(text("CREATE TABLE IF NOT EXISTS test (id INTEGER)"))
            await session.execute(text("INSERT INTO test VALUES (42)"))
            return {"written": True}

        @app.get("/db-read")
        async def db_read(container: DepContainer):
            session = await container.aget(AsyncSession)
            result = await session.execute(text("SELECT id FROM test"))
            return {"value": result.scalar()}

        return {}


async def test_database_extension_registers_services():
    app, _, _ = build_app(
        DatabaseExtension(sqlite_settings()),
        DatabaseConsumerExtension(),
    )

    with TestClient(app) as client:
        resp = client.get("/db-test")
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"value": 1}


async def test_database_session_commits():
    app, _, _ = build_app(
        DatabaseExtension(sqlite_settings()),
        DatabaseConsumerExtension(),
    )

    with TestClient(app) as client:
        resp = client.get("/db-write")
        assert resp.status_code == 200, resp.text

        resp = client.get("/db-read")
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"value": 42}


def test_database_cli_registered():
    _, cli, _ = build_app(DatabaseExtension(sqlite_settings()))

    runner = CliRunner()
    result = runner.invoke(cli, ["db", "--help"])

    assert result.exit_code == 0
    assert "upgrade" in result.output
    assert "downgrade" in result.output
    assert "check" in result.output


def test_database_cli_check():
    _, cli, _ = build_app(DatabaseExtension(sqlite_settings()))

    runner = CliRunner()
    result = runner.invoke(cli, ["db", "check"])

    assert result.exit_code == 0
    assert "✓" in result.output
