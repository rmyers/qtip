"""
Health check endpoints using svcs ping capabilities.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

import structlog
import svcs
from fastapi import APIRouter, FastAPI, Request
from pydantic import BaseModel

from ..core.extensions import BaseExtension
from ..core.settings import Settings

log = structlog.get_logger()
health_router = APIRouter()


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"


class ServiceHealth(BaseModel):
    name: str
    status: HealthStatus
    message: str | None = None


class HealthResponse(BaseModel):
    status: HealthStatus
    version: str | None = None
    services: list[ServiceHealth] = []


@health_router.get("", response_model=HealthResponse)
async def health(
    services: svcs.fastapi.DepContainer, request: Request
) -> HealthResponse:
    """Full health check - pings all registered services."""
    pings = services.get_pings()

    _services: list[ServiceHealth] = []
    overall_healthy = True

    for ping in pings:
        try:
            await ping.aping()
            _services.append(
                ServiceHealth(
                    name=ping.name,
                    status=HealthStatus.HEALTHY,
                )
            )
        except Exception as e:
            log.warning("health_check_failed", service=ping.name, error=str(e))
            _services.append(
                ServiceHealth(
                    name=ping.name,
                    status=HealthStatus.UNHEALTHY,
                    message=str(e),
                )
            )
            overall_healthy = False

    return HealthResponse(
        status=(HealthStatus.HEALTHY if overall_healthy else HealthStatus.UNHEALTHY),
        version=getattr(request.state, "version", "NA"),
        services=_services,
    )


@health_router.get("/live")
async def liveness() -> dict[str, str]:
    """Liveness probe - is the process running?"""
    return {"status": "ok"}


@health_router.get("/ready")
async def readiness(services: svcs.fastapi.DepContainer) -> dict[str, str]:
    """Readiness probe - can we serve traffic?"""
    from fastapi import HTTPException

    pings = services.get_pings()

    for ping in pings:
        try:
            await ping.aping()
        except Exception as e:
            log.warning("readiness_check_failed", service=ping.name, error=str(e))
            raise HTTPException(status_code=503, detail=f"{ping.name} unhealthy")

    return {"status": "ok"}


class HealthExtension(BaseExtension):
    """
    Health check extension using svcs pings.

    Adds:
        GET /healthz       - Full health check using svcs pings
        GET /healthz/live  - Liveness probe (always 200)
        GET /healthz/ready - Readiness probe (503 if unhealthy)

    Settings:
        - `health_enabled`: bool to disable health routes, default True
        - `health_prefix`: prefix to include routes default: '/healthz'
        - `version`: used to display in the response
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()

    async def startup(self, registry: svcs.Registry, app: FastAPI) -> dict[str, Any]:
        state = await super().startup(registry, app)
        state["version"] = self.settings.version
        return state

    def add_routes(self, app: FastAPI) -> None:
        if self.settings.health_enabled:
            app.include_router(
                health_router,
                prefix=self.settings.health_prefix,
                tags=["health"],
            )
