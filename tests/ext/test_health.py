from typing import Any, AsyncGenerator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from svcs import Registry

from cuneus import build_app, BaseExtension
from cuneus.core.settings import Settings
from cuneus.ext import health


class Service:
    """Mock service for type registration"""

    magic = 42


@asynccontextmanager
async def get_service() -> AsyncGenerator[Service, None]:
    yield Service()


async def healthy_ping(svc: Service) -> None:
    pass


async def unhealthy_ping(svc: Service) -> None:
    raise ConnectionError("Database unavailable")


class HealthyExtension(BaseExtension):
    async def startup(self, registry: Registry, app: FastAPI) -> dict[str, Any]:
        registry.register_factory(Service, get_service, ping=healthy_ping)
        return await super().startup(registry, app)


class UnhealthyExtension(BaseExtension):
    async def startup(self, registry: Registry, app: FastAPI) -> dict[str, Any]:
        registry.register_factory(Service, get_service, ping=unhealthy_ping)
        return await super().startup(registry, app)


async def test_health_endpoints():
    app, _, _ = build_app(HealthyExtension)

    with TestClient(app) as client:
        resp = client.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == health.HealthStatus.HEALTHY

        resp = client.get("/healthz/live")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

        resp = client.get("/healthz/ready")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


async def test_health_unhealthy_service():
    app, _, _ = build_app(UnhealthyExtension)

    with TestClient(app) as client:
        resp = client.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == health.HealthStatus.UNHEALTHY
        assert data["services"][0]["status"] == health.HealthStatus.UNHEALTHY
        assert "Database unavailable" in data["services"][0]["message"]


async def test_readiness_unhealthy_returns_503():
    app, _, _ = build_app(UnhealthyExtension)

    with TestClient(app) as client:
        resp = client.get("/healthz/ready")
        assert resp.status_code == 503
        assert "unhealthy" in resp.json()["detail"]


async def test_health_disabled():
    settings = Settings(health_enabled=False)
    app, _, _ = build_app(HealthyExtension, settings=settings)

    with TestClient(app) as client:
        resp = client.get("/healthz")
        assert resp.status_code == 404


async def test_health_custom_prefix():
    settings = Settings(health_prefix="/status")
    app, _, _ = build_app(HealthyExtension, settings=settings)

    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 404
        assert client.get("/status").status_code == 200
        assert client.get("/status/live").status_code == 200


async def test_health_includes_version():
    settings = Settings(version="1.2.3")
    app, _, _ = build_app(HealthyExtension, settings=settings)

    with TestClient(app) as client:
        resp = client.get("/healthz")
        assert resp.json()["version"] == "1.2.3"
