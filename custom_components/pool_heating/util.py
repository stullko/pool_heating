"""Shared pure helpers (no Home Assistant imports).

Time handling: SHMU timestamps are Unix UTC. Night / active windows and all
user-facing strings are local (Europe/Bratislava), DST-aware via zoneinfo.
"""

from __future__ import annotations

from datetime import datetime, time, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - py<3.9 fallback, never on modern HA
    ZoneInfo = None  # type: ignore[assignment]

from .const import TIMEZONE

UTC = timezone.utc


def _local_tz():
    if ZoneInfo is not None:
        try:
            return ZoneInfo(TIMEZONE)
        except Exception:  # pragma: no cover - bad tz database
            return UTC
    return UTC  # pragma: no cover


LOCAL_TZ = _local_tz()


def as_utc(dt: datetime) -> datetime:
    """Return a timezone-aware datetime in UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_local(dt: datetime) -> datetime:
    """Convert a (naive=UTC or aware) datetime to local time."""
    return as_utc(dt).astimezone(LOCAL_TZ)


def parse_hhmm(value: str | time) -> time:
    """Parse 'HH:MM' or 'HH:MM:SS' into a time. Accepts a time unchanged."""
    if isinstance(value, time):
        return value
    parts = str(value).split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0
    second = int(parts[2]) if len(parts) > 2 else 0
    return time(hour=hour, minute=minute, second=second)


def in_time_window(t: time, start: time, end: time) -> bool:
    """True if local time t is within [start, end), handling midnight wrap."""
    if start == end:
        return False
    if start < end:
        return start <= t < end
    # window wraps past midnight, e.g. 21:00 -> 08:00
    return t >= start or t < end


def is_active_hour(dt_utc: datetime, active_start, active_end) -> bool:
    """True if the local time of dt_utc falls inside the daytime active window."""
    local_t = to_local(dt_utc).time()
    return in_time_window(local_t, parse_hhmm(active_start), parse_hhmm(active_end))


def is_night(dt_utc: datetime, night_start, night_end) -> bool:
    """True if the local time of dt_utc falls inside the night (pump-off) window."""
    local_t = to_local(dt_utc).time()
    return in_time_window(local_t, parse_hhmm(night_start), parse_hhmm(night_end))


def hour_floor_ts(ts: int) -> int:
    """Floor a Unix timestamp to the start of its hour."""
    return ts - (ts % 3600)
