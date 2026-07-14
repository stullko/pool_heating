"""Smoke tests for Home Assistant platform module imports."""

import os
import subprocess
import sys
from importlib import import_module

from custom_components.pool_heating import const as C

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_platform_modules_import() -> None:
    """Ensure Home Assistant can import every forwarded platform."""
    for platform in C.PLATFORMS:
        import_module(f"custom_components.pool_heating.{platform}")


def test_pure_modules_import_without_homeassistant() -> None:
    """scripts/live_check.py promises to run with just aiohttp installed."""
    code = (
        "import sys\n"
        "class _Block:\n"
        "    def find_spec(self, name, *args):\n"
        "        if name == 'homeassistant' or name.startswith('homeassistant.'):\n"
        "            raise ImportError('homeassistant blocked')\n"
        "        return None\n"
        "sys.meta_path.insert(0, _Block())\n"
        "from custom_components.pool_heating import (\n"
        "    const, decision, forecast, model, options, shmu, util)\n"
        "print('pure-ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=_REPO_ROOT, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "pure-ok" in result.stdout
