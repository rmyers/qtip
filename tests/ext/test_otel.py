# tests/ext/test_otel.py
from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import Tracer
from starlette.testclient import TestClient
from svcs import Registry
from svcs.fastapi import DepContainer

from cuneus import build_app, BaseExtension
from cuneus.ext.otel import OTelExtension, OTelSettings


class InMemorySpanExporter(SpanExporter):
    """Stores spans in memory for testing."""

    def __init__(self):
        self.spans: list = []

    def export(self, spans):
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self):
        pass


def otel_settings() -> OTelSettings:
    """Test settings with auto-instrumentation disabled."""
    return OTelSettings(
        service_name="test-service",
        service_version="1.0.0",
        instrument_fastapi=False,
        instrument_sqlalchemy=False,
        instrument_httpx=False,
        instrument_redis=False,
        instrument_logging=False,
    )


class TracingConsumerExtension(BaseExtension):
    """Extension that uses tracing."""

    async def startup(self, registry: Registry, app: FastAPI) -> dict[str, Any]:
        @app.get("/traced")
        async def traced_endpoint(container: DepContainer):
            tracer = await container.aget(Tracer)
            with tracer.start_as_current_span("test-span") as span:
                span.set_attribute("test.value", 42)
            return {"traced": True}

        return {}


@pytest.fixture(autouse=True)
def reset_otel():
    """Reset OTel global state between tests."""
    yield
    trace._TRACER_PROVIDER_SET_ONCE._done = False
    trace._TRACER_PROVIDER = None


async def test_otel_extension_registers_tracer():
    exporter = InMemorySpanExporter()

    app, _, _ = build_app(
        OTelExtension(otel_settings(), span_exporters=[exporter]),
        TracingConsumerExtension(),
    )

    with TestClient(app) as client:
        resp = client.get("/traced")
        assert resp.status_code == 200
        assert resp.json() == {"traced": True}


async def test_otel_creates_spans():
    exporter = InMemorySpanExporter()

    app, _, lifespan = build_app(
        OTelExtension(otel_settings(), span_exporters=[exporter]),
        TracingConsumerExtension(),
    )

    with TestClient(app) as client:
        client.get("/traced")

        # Force flush via provider
        provider = lifespan.registry._services[Tracer].factory()
        # Get the tracer provider from global state
        trace.get_tracer_provider().force_flush()

    assert len(exporter.spans) >= 1
    span_names = [s.name for s in exporter.spans]
    assert "test-span" in span_names


async def test_otel_disabled():
    settings = OTelSettings(enabled=False)

    app, _, _ = build_app(OTelExtension(settings))

    with TestClient(app) as client:
        resp = client.get("/healthz")
        assert resp.status_code == 200


async def test_otel_excluded_paths():
    exporter = InMemorySpanExporter()
    settings = OTelSettings(
        service_name="test",
        excluded_paths=["/healthz", "/healthz/live", "/healthz/ready"],
        instrument_fastapi=False,
        instrument_sqlalchemy=False,
        instrument_httpx=False,
        instrument_redis=False,
        instrument_logging=False,
    )

    app, _, _ = build_app(OTelExtension(settings, span_exporters=[exporter]))

    with TestClient(app) as client:
        # Health endpoints should work but not create extra spans
        resp = client.get("/healthz")
        assert resp.status_code == 200
