from __future__ import annotations

import importlib
from typing import Any, Callable

import structlog
import svcs
from fastapi import FastAPI, Request, Response
from pydantic import Field
from pydantic_settings import SettingsConfigDict
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware

from ..core.extensions import BaseExtension, HasMiddleware
from ..core.settings import CuneusBaseSettings, DEFAULT_TOOL_NAME
from ..dependencies import Dependency, check_dependencies

check_dependencies(
    "cuneus.ext.otel",
    Dependency("opentelemetry.sdk", "opentelemetry-sdk"),
    Dependency("opentelemetry.trace", "opentelemetry-api"),
)

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider, SpanProcessor
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
from opentelemetry.trace import Tracer, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.propagate import set_global_textmap

logger = structlog.stdlib.get_logger(__name__)


class OTelSettings(CuneusBaseSettings):
    """OpenTelemetry configuration."""

    model_config = SettingsConfigDict(
        env_prefix="OTEL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        pyproject_toml_depth=2,
        pyproject_toml_table_header=("tool", DEFAULT_TOOL_NAME, "otel"),
    )

    # Service identity
    service_name: str = "unknown-service"
    service_version: str = "0.0.0"
    environment: str = "development"

    # Feature flags
    enabled: bool = True
    traces_enabled: bool = True
    metrics_enabled: bool = True

    # Auto-instrumentation
    instrument_fastapi: bool = True
    instrument_sqlalchemy: bool = True
    instrument_httpx: bool = True
    instrument_redis: bool = True
    instrument_logging: bool = True

    # Exporter
    exporter_otlp_endpoint: str | None = None

    # Sampling
    sample_rate: float = 1.0

    # Excluded paths
    excluded_paths: list[str] = Field(
        default_factory=lambda: ["/health", "/ready", "/metrics", "/favicon.ico"]
    )


class OTelExtension(BaseExtension, HasMiddleware):
    """
    OpenTelemetry extension providing distributed tracing and metrics.

    Registers:
        - TracerProvider: The global tracer provider
        - Tracer: A tracer instance for the service
        - MeterProvider: The global meter provider (if metrics enabled)

    Auto-instrumentation (configurable):
        - FastAPI/Starlette
        - SQLAlchemy
        - HTTPX
        - Redis
        - Logging

    Configuration (env with OTEL_ prefix or pyproject.toml [tool.cuneus.otel]):
        service_name: Service name for traces
        service_version: Service version
        environment: Deployment environment
        enabled: Enable/disable OTel entirely (default: true)
        traces_enabled: Enable tracing (default: true)
        metrics_enabled: Enable metrics (default: true)
        instrument_*: Enable specific auto-instrumentation
        exporter_otlp_endpoint: OTLP exporter endpoint
        sample_rate: Sampling rate 0.0-1.0 (default: 1.0)
        excluded_paths: Paths to exclude from tracing
    """

    _tracer_provider: TracerProvider
    _meter_provider: MeterProvider | None = None

    def __init__(
        self,
        settings: OTelSettings | None = None,
        span_exporters: list[SpanExporter] | None = None,
        span_processors: list[SpanProcessor] | None = None,
    ):
        self.settings = settings or OTelSettings()
        self._span_exporters = span_exporters or []
        self._span_processors = span_processors or []

    async def startup(self, registry: svcs.Registry, app: FastAPI) -> dict[str, Any]:
        if not self.settings.enabled:
            logger.info("OpenTelemetry disabled")
            return {}

        resource = Resource.create(
            {
                SERVICE_NAME: self.settings.service_name,
                SERVICE_VERSION: self.settings.service_version,
                "deployment.environment": self.settings.environment,
            }
        )

        if self.settings.traces_enabled:
            self._tracer_provider = TracerProvider(resource=resource)

            for processor in self._span_processors:
                self._tracer_provider.add_span_processor(processor)

            for exporter in self._span_exporters:
                self._tracer_provider.add_span_processor(BatchSpanProcessor(exporter))

            trace.set_tracer_provider(self._tracer_provider)
            set_global_textmap(TraceContextTextMapPropagator())

            registry.register_value(TracerProvider, self._tracer_provider)
            registry.register_value(
                Tracer,
                self._tracer_provider.get_tracer(self.settings.service_name),
            )

            self._setup_auto_instrumentation(app)

            logger.info(
                "OpenTelemetry tracing started",
                extra={
                    "service": self.settings.service_name,
                    "exporters": len(self._span_exporters),
                },
            )

        if self.settings.metrics_enabled:
            meter_provider = MeterProvider(resource=resource)
            metrics.set_meter_provider(meter_provider)
            self._meter_provider = meter_provider
            registry.register_value(MeterProvider, self._meter_provider)

        return {"tracer_provider": self._tracer_provider}

    async def shutdown(self, app: FastAPI) -> None:
        if self._tracer_provider:
            self._tracer_provider.shutdown()
            logger.info("OpenTelemetry shutdown")

    def middleware(self) -> list[Middleware]:
        if not self.settings.enabled or not self.settings.traces_enabled:
            return []

        return [
            Middleware(
                OTelMiddleware,
                excluded_paths=set(self.settings.excluded_paths),
            )
        ]

    def _setup_auto_instrumentation(self, app: FastAPI) -> None:
        """Setup auto-instrumentation based on settings."""
        instrumentors = [
            (
                self.settings.instrument_sqlalchemy,
                "opentelemetry.instrumentation.sqlalchemy",
                "SQLAlchemyInstrumentor",
            ),
            (
                self.settings.instrument_httpx,
                "opentelemetry.instrumentation.httpx",
                "HTTPXClientInstrumentor",
            ),
            (
                self.settings.instrument_redis,
                "opentelemetry.instrumentation.redis",
                "RedisInstrumentor",
            ),
        ]

        for enabled, module, class_name in instrumentors:
            if enabled:
                self._try_instrument(module, class_name)

        if self.settings.instrument_fastapi:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            inst = FastAPIInstrumentor()
            inst.instrument_app(
                app,
                tracer_provider=self._tracer_provider,
                meter_provider=self._meter_provider,
            )
            logger.debug("FastAPIInstrumentor auto-instrumentation enabled")

    def _try_instrument(self, module: str, class_name: str) -> None:
        try:
            mod = importlib.import_module(module)
            instrumentor = getattr(mod, class_name)()
            instrumentor.instrument()
            logger.debug(f"{class_name} auto-instrumentation enabled")
        except ImportError:
            logger.debug(f"{class_name} instrumentation not available")
        except Exception as e:
            logger.warning(f"{class_name} instrumentation failed: {e}")


class OTelMiddleware(BaseHTTPMiddleware):
    """Middleware to enrich spans and logs with trace context."""

    def __init__(self, app, excluded_paths: set[str] | None = None):
        super().__init__(app)
        self.excluded_paths = excluded_paths or set()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in self.excluded_paths:
            return await call_next(request)

        span = trace.get_current_span()
        ctx = span.get_span_context()

        # Bind trace context to structlog for this request
        if ctx.is_valid:
            structlog.contextvars.bind_contextvars(
                trace_id=format(ctx.trace_id, "032x"),
                span_id=format(ctx.span_id, "016x"),
            )

        if span.is_recording():
            # span.set_attribute("http.client_ip", _get_client_ip(request))
            span.set_attribute("http.user_agent", request.headers.get("user-agent", ""))

            if request.url.query:
                span.set_attribute("http.query_string", str(request.url.query))

            if request_id := request.headers.get("x-request-id"):
                span.set_attribute("http.request_id", request_id)

        try:
            response = await call_next(request)

            if span.is_recording():
                if content_length := response.headers.get("content-length"):
                    span.set_attribute(
                        "http.response_content_length", int(content_length)
                    )

            return response

        except Exception as exc:
            if span.is_recording():
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                span.record_exception(exc)
            raise

        finally:
            structlog.contextvars.unbind_contextvars("trace_id", "span_id")
