import pytest
from click.testing import CliRunner
from unittest.mock import patch, MagicMock

from cuneus.cli import (
    import_from_string,
    get_user_cli,
    cli,
    dev,
    prod,
    routes,
    CuneusCLI,
    main,
)


class TestImportFromString:
    def test_imports_module_attribute(self):
        result = import_from_string("os.path:join")
        from os.path import join

        assert result is join

    def test_raises_on_missing_colon(self):
        with pytest.raises(ValueError, match="missing function"):
            import_from_string("os.path.join")

    def test_raises_on_invalid_module(self):
        with pytest.raises(ModuleNotFoundError):
            import_from_string("nonexistent.module:func")

    def test_raises_on_invalid_attribute(self):
        with pytest.raises(AttributeError):
            import_from_string("os.path:nonexistent_func")

    def test_adds_cwd_to_path(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        # Create a temp module
        (tmp_path / "temp_module.py").write_text("my_var = 42")

        result = import_from_string("temp_module:my_var")
        assert result == 42


class TestGetUserCli:
    def test_returns_none_on_import_error(self):
        with patch("cuneus.cli.Settings") as mock_settings:
            mock_settings.return_value.cli_module = "nonexistent:cli"
            result = get_user_cli()
            assert result is None

    def test_returns_cli_on_success(self):
        import click

        @click.group()
        def user_cli():
            pass

        with (
            patch("cuneus.cli.Settings") as mock_settings,
            patch("cuneus.cli.import_from_string", return_value=user_cli),
        ):
            mock_settings.return_value.cli_module = "myapp:cli"
            result = get_user_cli()
            assert result is user_cli


class TestCliCommands:
    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_cli_help(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Cuneus CLI" in result.output

    def test_dev_command(self, runner):
        with (
            patch("cuneus.cli.Settings") as mock_settings,
            patch("uvicorn.run") as mock_run,
        ):
            mock_settings.return_value.app_module = "myapp:app"

            result = runner.invoke(dev, ["--host", "127.0.0.1", "--port", "3000"])

            assert result.exit_code == 0
            mock_run.assert_called_once_with(
                "myapp:app",
                host="127.0.0.1",
                port=3000,
                reload=True,
                log_config=None,
                server_header=False,
            )

    def test_dev_command_defaults(self, runner):
        with (
            patch("cuneus.cli.Settings") as mock_settings,
            patch("uvicorn.run") as mock_run,
        ):
            mock_settings.return_value.app_module = "myapp:app"

            result = runner.invoke(dev)

            assert result.exit_code == 0
            mock_run.assert_called_once_with(
                "myapp:app",
                host="0.0.0.0",
                port=8000,
                reload=True,
                log_config=None,
                server_header=False,
            )

    def test_prod_command(self, runner):
        with (
            patch("cuneus.cli.Settings") as mock_settings,
            patch("uvicorn.run") as mock_run,
        ):
            mock_settings.return_value.app_module = "myapp:app"

            result = runner.invoke(prod, ["--workers", "4"])

            assert result.exit_code == 0
            mock_run.assert_called_once_with(
                "myapp:app",
                host="0.0.0.0",
                port=8000,
                workers=4,
                log_config=None,
                server_header=False,
            )

    def test_routes_command(self, runner):
        mock_app = MagicMock()
        mock_route = MagicMock()
        mock_route.methods = {"GET", "HEAD", "OPTIONS"}
        mock_route.path = "/users"
        mock_app.routes = [mock_route]

        with (
            patch("cuneus.cli.Settings") as mock_settings,
            patch("cuneus.cli.import_from_string", return_value=mock_app),
        ):
            mock_settings.return_value.app_module = "myapp:app"

            result = runner.invoke(routes)

            assert result.exit_code == 0
            assert "GET" in result.output
            assert "/users" in result.output
            assert "HEAD" not in result.output


class TestCuneusCLI:
    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_has_base_commands(self):
        cli = CuneusCLI()
        commands = cli.list_commands(None)  # type: ignore
        assert "dev" in commands
        assert "prod" in commands
        assert "routes" in commands

    def test_merges_user_commands(self):
        import click

        @click.group()
        def user_cli():
            pass

        @user_cli.command()
        def custom():
            click.echo("custom command")

        cli = CuneusCLI()
        cli._user_cli = user_cli
        cli._user_cli_loaded = True

        commands = cli.list_commands(None)  # type: ignore
        assert "dev" in commands
        assert "custom" in commands

    def test_user_cli_takes_priority(self):
        import click

        @click.group()
        def user_cli():
            pass

        @user_cli.command()
        def dev():
            click.echo("user dev")

        cli = CuneusCLI()
        cli._user_cli = user_cli
        cli._user_cli_loaded = True

        ctx = click.Context(cli)
        cmd = cli.get_command(ctx, "dev")
        assert cmd is not None

        # Should get user's dev, not base dev
        runner = CliRunner()
        result = runner.invoke(cmd)
        assert "user dev" in result.output

    def test_falls_back_to_base_command(self):
        import click

        @click.group()
        def user_cli():
            pass

        cli = CuneusCLI()
        cli._user_cli = user_cli
        cli._user_cli_loaded = True

        ctx = click.Context(cli)
        cmd = cli.get_command(ctx, "routes")

        assert cmd is not None
        assert cmd.name == "routes"

    def test_lazy_loads_user_cli(self):
        cli = CuneusCLI()
        assert cli._user_cli_loaded is False

        with patch("cuneus.cli.get_user_cli", return_value=None) as mock_get:
            _ = cli.user_cli
            mock_get.assert_called_once()
            assert cli._user_cli_loaded is True

            # Second access doesn't reload
            _ = cli.user_cli
            mock_get.assert_called_once()


class TestMain:
    def test_main_is_cuneus_cli(self):
        assert isinstance(main, CuneusCLI)

    def test_main_help(self):
        runner = CliRunner()
        with patch.object(CuneusCLI, "user_cli", None):
            result = runner.invoke(main, ["--help"])
            assert result.exit_code == 0
            assert "Cuneus CLI" in result.output
