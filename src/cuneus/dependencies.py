# cuneus/core/dependencies.py
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Dependency:
    """A required dependency with install hint."""

    import_name: str
    package_name: str | None = None  # pip package name if different from import

    @property
    def pip_name(self) -> str:
        return self.package_name or self.import_name


class MissingDependencyError(ImportError):
    """Raised when required dependencies are not installed."""

    def __init__(self, extension: str, missing: list[Dependency]):
        self.extension = extension
        self.missing = missing
        packages = " ".join(d.pip_name for d in missing)
        super().__init__(
            f"{extension} requires additional dependencies. Install with: uv add {packages}"
        )


def check_dependencies(extension: str, *deps: Dependency) -> None:
    """
    Check that dependencies are installed, raise helpful error if not.

    Usage:
        from cuneus.core.dependencies import check_dependencies, Dependency

        check_dependencies(
            "DatabaseExtension",
            Dependency("sqlalchemy"),
            Dependency("asyncpg"),
        )
    """
    missing = []
    for dep in deps:
        try:
            importlib.import_module(dep.import_name)
        except ImportError:
            missing.append(dep)

    if missing:
        raise MissingDependencyError(extension, missing)


def warn_missing(extension: str, *deps: Dependency) -> list[Dependency]:
    """
    Check dependencies but only warn, don't raise. Returns list of missing.

    Useful for optional features within an extension.
    """
    missing = []
    for dep in deps:
        try:
            importlib.import_module(dep.import_name)
        except ImportError:
            missing.append(dep)

    if missing:
        packages = " ".join(d.pip_name for d in missing)
        logger.warning(
            f"{extension}: optional dependencies not installed. "
            f"Some features disabled. Install with: uv add {packages}"
        )

    return missing
