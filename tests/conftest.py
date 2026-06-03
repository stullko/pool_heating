"""Test configuration: make the repo root importable for custom_components."""

import os
import sys

import pytest

try:
    import pytest_socket
except ModuleNotFoundError:
    pytest_socket = None

if sys.platform == "win32" and pytest_socket is not None:

    def _windows_disable_socket(*args, **kwargs):
        """Keep sockets enabled so Windows asyncio can create socketpair."""
        pytest_socket.enable_socket()

    pytest_socket.disable_socket = _windows_disable_socket

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.hookimpl(trylast=True)
def pytest_runtest_setup(item):
    """Undo HA test harness socket blocking that breaks Windows socketpair."""
    if sys.platform != "win32" or pytest_socket is None:
        return
    pytest_socket.enable_socket()


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_fixture_setup(fixturedef, request):
    """Enable sockets before pytest-asyncio creates a Windows event loop."""
    needs_windows_socket_pair = fixturedef.argname == "event_loop" or (
        fixturedef.argname.startswith("_")
        and fixturedef.argname.endswith("_scoped_runner")
    )
    if sys.platform == "win32" and pytest_socket is not None and needs_windows_socket_pair:
        pytest_socket.enable_socket()
    yield
