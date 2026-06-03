"""Windows-only test stub for Home Assistant's runner import."""

LOCK_EX = 2
LOCK_NB = 4


def flock(fd, operation):
    """No-op file lock used only when running the HA pytest harness on Windows."""
    return None
