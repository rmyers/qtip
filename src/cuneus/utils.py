import importlib
import typing


def import_from_string(import_str: str) -> typing.Any:
    """Import an object from a module:attribute string."""
    module_path, _, attr = import_str.partition(":")
    if not attr:
        raise ValueError(f"module_path missing function {import_str} expecting 'module.path:name'")

    module = importlib.import_module(module_path)
    return getattr(module, attr)
