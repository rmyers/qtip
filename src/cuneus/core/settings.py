from __future__ import annotations

import pathlib
import sys
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    PyprojectTomlConfigSettingsSource,
    SettingsConfigDict,
)

DEFAULT_TOOL_NAME = "cuneus"


class CuneusBaseSettings(BaseSettings):
    """
    Base settings that loads from:
    1. pyproject.toml [tool.cuneus] (lowest priority)
    2. .env file
    3. Environment variables (highest priority)
    """

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            PyprojectTomlConfigSettingsSource(settings_cls),
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )


class Settings(CuneusBaseSettings):

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="allow",
        pyproject_toml_depth=2,
        pyproject_toml_table_header=("tool", DEFAULT_TOOL_NAME),
    )

    app_name: str = "app"
    app_module: str = "app.main:app"
    cli_module: str = "app.main:cli"
    debug: bool = False
    version: str | None = None

    # logging
    log_level: str = "INFO"
    log_json: bool = False
    log_server_errors: bool = True
    request_id_header: str = "X-Request-ID"

    # health
    health_enabled: bool = True
    health_prefix: str = "/healthz"

    @classmethod
    def get_project_root(cls) -> pathlib.Path:
        """
        Get the project root by inspecting where pydantic-settings
        found the pyproject.toml file.
        """
        source = PyprojectTomlConfigSettingsSource(
            cls,
        )
        if source.toml_file_path:
            return source.toml_file_path.parent
        return pathlib.Path.cwd()


def ensure_project_in_path() -> None:
    """Add project root to sys.path if not already present."""
    project_root = str(Settings.get_project_root())
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
