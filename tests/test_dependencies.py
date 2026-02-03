from __future__ import annotations

import pytest

from cuneus.dependencies import (
    Dependency,
    MissingDependencyError,
    check_dependencies,
    warn_missing,
)


def test_dependency_pip_name_defaults_to_import():
    dep = Dependency("sqlalchemy")
    assert dep.pip_name == "sqlalchemy"


def test_dependency_pip_name_override():
    dep = Dependency("opentelemetry.sdk", "opentelemetry-sdk")
    assert dep.pip_name == "opentelemetry-sdk"


def test_check_dependencies_passes_when_installed():
    # These should always be available in test env
    check_dependencies(
        "TestExtension",
        Dependency("os"),
        Dependency("sys"),
    )


def test_check_dependencies_raises_when_missing():
    with pytest.raises(MissingDependencyError) as exc_info:
        check_dependencies(
            "TestExtension",
            Dependency("nonexistent_package_xyz"),
        )

    assert "TestExtension" in str(exc_info.value)
    assert "uv add nonexistent_package_xyz" in str(exc_info.value)


def test_check_dependencies_lists_all_missing():
    with pytest.raises(MissingDependencyError) as exc_info:
        check_dependencies(
            "TestExtension",
            Dependency("nonexistent_one"),
            Dependency("nonexistent_two", "nonexistent-two-pkg"),
        )

    msg = str(exc_info.value)
    assert "nonexistent_one" in msg
    assert "nonexistent-two-pkg" in msg


def test_check_dependencies_partial_missing():
    with pytest.raises(MissingDependencyError) as exc_info:
        check_dependencies(
            "TestExtension",
            Dependency("os"),  # exists
            Dependency("nonexistent_package_xyz"),  # missing
        )

    # Should only mention the missing one
    assert "nonexistent_package_xyz" in str(exc_info.value)
    assert exc_info.value.missing[0].import_name == "nonexistent_package_xyz"


def test_missing_dependency_error_attributes():
    try:
        check_dependencies(
            "MyExtension",
            Dependency("fake_pkg", "fake-pkg"),
        )
    except MissingDependencyError as e:
        assert e.extension == "MyExtension"
        assert len(e.missing) == 1
        assert e.missing[0].import_name == "fake_pkg"
        assert e.missing[0].pip_name == "fake-pkg"


def test_warn_missing_returns_missing_list():
    missing = warn_missing(
        "TestExtension",
        Dependency("os"),  # exists
        Dependency("nonexistent_package_xyz"),  # missing
    )

    assert len(missing) == 1
    assert missing[0].import_name == "nonexistent_package_xyz"


def test_warn_missing_returns_empty_when_all_installed():
    missing = warn_missing(
        "TestExtension",
        Dependency("os"),
        Dependency("sys"),
    )

    assert missing == []


def test_warn_missing_logs_warning(caplog):
    with caplog.at_level("WARNING"):
        warn_missing(
            "TestExtension",
            Dependency("nonexistent_pkg", "nonexistent-pkg"),
        )

    assert "TestExtension" in caplog.text
    assert "nonexistent-pkg" in caplog.text
