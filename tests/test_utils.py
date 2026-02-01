import pytest

from cuneus.utils import import_from_string


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
