# tests/cli/test_cli_integration.py
"""Integration tests for the cuneus CLI."""

import sys
from pathlib import Path

import pytest
from click.testing import CliRunner


TEST_APP_DIR = Path(__file__).parent / "testapp"


@pytest.fixture
def cli_runner():
    return CliRunner()


@pytest.fixture
def test_app(cli_runner, tmp_path):
    """Set up isolated test app environment."""
    import shutil

    with cli_runner.isolated_filesystem(temp_dir=tmp_path):
        # Copy pyproject.toml, main.py, etc. to project root (cwd)
        shutil.copytree(TEST_APP_DIR, Path.cwd(), dirs_exist_ok=True)

        for mod in list(sys.modules):
            if mod.startswith(("main", "cuneus.cli")):
                del sys.modules[mod]

        yield Path.cwd()


class TestCLIDiscovery:
    def test_discovers_app_commands(self, cli_runner, test_app):
        from cuneus.cli import CuneusCLI

        cli = CuneusCLI()
        commands = cli.list_commands(None)  # type: ignore

        assert "dev" in commands
        assert "prod" in commands
        assert "routes" in commands
        assert "custom" in commands

    def test_custom_command_executes(self, cli_runner, test_app):
        from cuneus.cli import CuneusCLI

        cli = CuneusCLI()
        result = cli_runner.invoke(cli, ["custom"])

        assert result.exit_code == 0
        assert "custom command executed" in result.output

    def test_help_shows_all_commands(self, cli_runner, test_app):
        from cuneus.cli import CuneusCLI

        cli = CuneusCLI()
        result = cli_runner.invoke(cli, ["--help"])

        assert result.exit_code == 0
        assert "dev" in result.output
        assert "custom" in result.output


class TestBuiltInCommands:
    def test_routes_command_lists_routes(self, cli_runner, test_app):
        from cuneus.cli import CuneusCLI

        cli = CuneusCLI()
        result = cli_runner.invoke(cli, ["routes"])

        assert result.exit_code == 0
        assert "/hello" in result.output
        assert "/healthz" in result.output

    def test_dev_command_starts_uvicorn(self, cli_runner, test_app, mocker):
        mock_run = mocker.patch("uvicorn.run")

        from cuneus.cli import CuneusCLI

        cli = CuneusCLI()
        result = cli_runner.invoke(cli, ["dev", "--host", "127.0.0.1", "--port", "9000"])

        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["host"] == "127.0.0.1"
        assert call_kwargs["port"] == 9000
        assert call_kwargs["reload"] is True

    def test_prod_command_starts_uvicorn(self, cli_runner, test_app, mocker):
        mock_run = mocker.patch("uvicorn.run")

        from cuneus.cli import CuneusCLI

        cli = CuneusCLI()
        result = cli_runner.invoke(cli, ["prod", "--workers", "4"])

        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["workers"] == 4


class TestCLIFromSubdirectory:
    def test_discovers_pyproject_from_subdirectory(self, cli_runner: CliRunner, test_app):
        import os

        subdir = test_app / "src" / "nested"
        subdir.mkdir(parents=True)
        os.chdir(subdir)

        for mod in list(sys.modules):
            if mod.startswith(("main", "cuneus.cli")):
                del sys.modules[mod]

        from cuneus.cli import CuneusCLI

        cli = CuneusCLI()
        commands = cli.list_commands(None)  # type: ignore

        assert "custom" in commands


class TestCLIMissingConfig:
    def test_handles_missing_pyproject(self, cli_runner, tmp_path):
        with cli_runner.isolated_filesystem(temp_dir=tmp_path):
            for mod in list(sys.modules):
                if mod.startswith("cuneus.cli"):
                    del sys.modules[mod]

            from cuneus.cli import CuneusCLI

            cli = CuneusCLI()
            result = cli_runner.invoke(cli, ["--help"])

            assert result.exit_code == 0
            result = cli_runner.invoke(cli, ["dev"])
            assert result.exit_code == 2
