"""
Structured logging with structlog and request context.
"""

from __future__ import annotations

import importlib
import logging
import shutil
import time
import uuid
from typing import Any, Awaitable, Callable

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware import Middleware
from starlette.types import ASGIApp

from .extensions import BaseExtension
from .settings import Settings

logger = structlog.stdlib.get_logger("cuneus")


def _get_suppress_modules():
    """Return the modules for rich to suppress.

    This helps reduce the amount of noise that we get from the traceback
    """
    modules = []
    for name in [
        "starlette",
        "fastapi",
        "asyncio",
        "anyio",
        "uvicorn",
        "opentelemetry.instrumentation.fastapi",
        "opentelemetry.instrumentation.asgi",
    ]:
        try:
            modules.append(importlib.import_module(name))
        except ImportError:
            pass
    return modules


def _get_exception_formatter() -> Any:
    """Use rich if available, with sane defaults. Otherwise plain."""
    try:
        import rich  # type: ignore

        return structlog.dev.RichTracebackFormatter(
            max_frames=5,
            show_locals=True,
            suppress=_get_suppress_modules(),
        )
    except ImportError:
        return structlog.dev.plain_traceback


def add_otel_context(
    logger: structlog.types.WrappedLogger,
    method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Add trace context at log time, replace request_id if present."""
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        ctx = span.get_span_context()

        if ctx.is_valid:
            event_dict["trace_id"] = format(ctx.trace_id, "032x")[:12]
            # Remove request_id - trace_id is the correlation now
            event_dict.pop("request_id", None)
    except ImportError:
        pass

    return event_dict


def configure_structlog(settings: Settings | None = None) -> None:
    log_settings = settings or Settings()

    # Shared processors
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        add_otel_context,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.UnicodeDecoder(),
    ]

    renderer = structlog.processors.JSONRenderer()

    if not log_settings.log_json:  # pragma: no branch
        term_width = shutil.get_terminal_size().columns
        pad_event = term_width - 36
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer(
            colors=True,
            pad_event_to=pad_event,
            exception_formatter=_get_exception_formatter(),
        )

    # Configure structlog
    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Create formatter for stdlib
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    # Configure root logger
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_settings.log_level.upper())

    # Quiet noisy loggers
    logging.getLogger("uvicorn.access").setLevel(logging.CRITICAL)
    logging.getLogger("svcs").setLevel(logging.INFO)


class LoggingExtension(BaseExtension):
    """
    Structured logging extension using structlog.

    Integrates with stdlib logging so uvicorn and other libraries
    also output through structlog.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        configure_structlog(settings)

    def middleware(self) -> list[Middleware]:
        return [
            Middleware(
                LoggingMiddleware,
                header_name=self.settings.request_id_header,
            ),
        ]


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware that:
    - Generates request_id
    - Binds it to structlog context
    - Logs request start/end
    - Adds request_id to response headers
    """

    def __init__(self, app: ASGIApp, header_name: str = "X-Request-ID") -> None:
        self.header_name = header_name
        super().__init__(app)

    async def dispatch(
        self, request: Request, call_next: Callable[..., Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        # Exclude health routes as these are just noise
        # TODO(rmyers): make this configurable
        if path.startswith("/health"):
            return await call_next(request)

        request_id = request.headers.get(self.header_name) or str(uuid.uuid4())[:8]

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=path,
        )

        request.state.request_id = request_id

        log = structlog.stdlib.get_logger("cuneus")
        start_time = time.perf_counter()

        try:
            response = await call_next(request)

            duration_ms = (time.perf_counter() - start_time) * 1000
            log.info(
                f"{request.method} {request.url.path} {response.status_code}",
                status_code=response.status_code,
                duration_ms=round(duration_ms, 2),
            )

            response.headers[self.header_name] = request_id
            return response

        except Exception:
            raise
        finally:
            structlog.contextvars.clear_contextvars()
