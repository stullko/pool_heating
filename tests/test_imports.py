"""Smoke tests for Home Assistant platform module imports."""

from importlib import import_module

from custom_components.pool_heating import const as C


def test_platform_modules_import() -> None:
    """Ensure Home Assistant can import every forwarded platform."""
    for platform in C.PLATFORMS:
        import_module(f"custom_components.pool_heating.{platform}")
