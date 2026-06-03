"""Windows-only test stub for Home Assistant's runner import."""

RLIMIT_NOFILE = 7


def getrlimit(resource):
    """Return a conservative no-op file descriptor limit."""
    return (2048, 2048)


def setrlimit(resource, limits):
    """No-op resource limit setter used only by Windows tests."""
    return None
