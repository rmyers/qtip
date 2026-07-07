# cuneus

> _The wedge stone that locks the arch together_

**cuneus** is a lightweight lifespan manager for FastAPI applications. It provides a simple pattern for composing extensions that handle startup/shutdown, service registration, and CLI commands.

The name comes from Roman architecture: a _cuneus_ is the wedge-shaped stone in a Roman arch. Each stone is simple on its own, but together they lock under pressure to create structures that have stood for millennia—no rebar required.


## Installation

```bash
pip install cuneus
```

With optional dependencies:

```bash
pip install cuneus[database]  # SQLAlchemy, asyncpg, alembic
pip install cuneus[all]       # Everything
```

## Quick Start (Usage)

```python
# app/main.py
from cuneus import build_app, Settings

app, cli, lifespan = build_app(
    settings=Settings(),
    title="My App",
)

@app.get("/")
async def hello():
    return {"message": "Hello, World!"}

__all__ = ["app", "cli", "lifespan"]
```

Run with:

```bash
uvicorn app.main:app --reload
```

Or use the CLI:

```bash
cuneus run     # Start the server
cuneus --help  # Show available commands
```

## What You Get

Out of the box, `build_app()` includes:

- **Structured logging** via structlog with request context
- **Health endpoints** at `/healthz`, `/healthz/live`, `/healthz/ready`
- **Request ID** tracking via `X-Request-ID` header
- **Exception handling** with proper error responses
- **CLI** with `run` command and extension hooks

## Database Extension

```python
from cuneus import build_app
from cuneus.ext.database import DatabaseExtension

app, cli, lifespan = build_app(
    DatabaseExtension(),
)
```

Configuration via environment or `pyproject.toml`:

```bash
DATABASE_DRIVER=postgresql+asyncpg
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_NAME=myapp
DATABASE_USERNAME=myapp
DATABASE_PASSWORD=secret
```

```toml
# pyproject.toml
[tool.cuneus.database]
driver = "postgresql+asyncpg"
host = "localhost"
name = "myapp"
```

CLI commands:

```bash
cuneus db upgrade          # Run migrations
cuneus db downgrade        # Rollback one migration
cuneus db revision -m "x"  # Create new migration
cuneus db current          # Show current revision
cuneus db check            # Test database connectivity
```

Use in routes:

```python
from sqlalchemy.ext.asyncio import AsyncSession
from svcs.fastapi import DepContainer

@app.get("/users")
async def get_users(container: DepContainer):
    session = await container.aget(AsyncSession)
    result = await session.execute(select(User))
    return result.scalars().all()
```

## OpenTelemetry Extension

```python
from cuneus import build_app
from cuneus.ext.otel import OTelExtension, OTelSettings

app, cli, lifespan = build_app(
    OTelExtension(
        settings=OTelSettings(service_name="my-service"),
        span_exporters=[your_exporter],
    ),
)
```

Configuration:

```bash
OTEL_SERVICE_NAME=my-service
OTEL_ENVIRONMENT=production
OTEL_INSTRUMENT_FASTAPI=true
OTEL_INSTRUMENT_SQLALCHEMY=true
```

Features:

- Automatic FastAPI/Starlette instrumentation
- Auto-instrumentation for SQLAlchemy, HTTPX, Redis
- W3C Trace Context propagation (`traceparent` header)
- Trace context in structlog (logs include `trace_id`)

## Creating Extensions

Use `BaseExtension` for simple cases:

```python
from cuneus import BaseExtension
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
import svcs

class MyExtension(BaseExtension):
    async def startup(self, registry: svcs.Registry, app: FastAPI) -> dict[str, Any]:
        engine = create_async_engine(self.settings.database_url)
        registry.register_value(AsyncEngine, engine)
        return {"engine": engine}

    async def shutdown(self, app: FastAPI) -> None:
        # Cleanup
        pass

    def middleware(self) -> list[Middleware]:
        return [Middleware(MyMiddleware)]

    def register_cli(self, cli_group: click.Group) -> None:
        @cli_group.command()
        def my_command():
            click.echo("Hello!")
```

### Extension Protocols

Extensions can implement multiple protocols:

| Protocol              | Method                    | Purpose                       |
| --------------------- | ------------------------- | ----------------------------- |
| `Extension`           | `register()`              | Lifecycle management          |
| `HasMiddleware`       | `middleware()`            | Add middleware                |
| `HasCLI`              | `register_cli()`          | Add CLI commands              |
| `HasRoutes`           | `add_routes()`            | Add routes after app creation |
| `HasExceptionHandler` | `add_exception_handler()` | Add exception handlers        |
| `HasPostAppHook`      | `post_app_hook()`         | Modify app after creation     |

## Testing

The lifespan exposes a `.registry` attribute for test overrides:

```python
from starlette.testclient import TestClient
from myapp import app, lifespan

def test_with_mock():
    with TestClient(app) as client:
        # Override a service
        mock_db = Mock(spec=Database)
        lifespan.registry.register_value(Database, mock_db)

        resp = client.get("/users")
        assert resp.status_code == 200
```

## Settings

cuneus uses pydantic-settings with multiple sources:

```python
from cuneus import Settings

class AppSettings(Settings):
    database_url: str = "sqlite+aiosqlite:///./app.db"

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        pyproject_toml_table_header=("tool", "myapp"),
    )
```

Load priority (highest wins):

1. Environment variables
2. `.env` file
3. `pyproject.toml`

## API Reference

### `build_app(*extensions, settings, **fastapi_kwargs)`

Build a FastAPI application with extensions.

Returns: `(app, cli, lifespan)`

### `BaseExtension`

Base class with hooks:

- `startup(registry, app) -> dict` — Setup resources
- `shutdown(app) -> None` — Cleanup resources
- `middleware() -> list[Middleware]` — Optional
- `register_cli(group) -> None` — Optional

### Built-in Extensions

| Extension            | Purpose                             |
| -------------------- | ----------------------------------- |
| `LoggingExtension`   | Structured logging, request context |
| `HealthExtension`    | Health check endpoints              |
| `ExceptionExtension` | Error handling                      |
| `ServerExtension`    | `run` CLI command                   |
| `DatabaseExtension`  | SQLAlchemy + Alembic                |
| `OTelExtension`      | OpenTelemetry tracing               |

## License

MIT

