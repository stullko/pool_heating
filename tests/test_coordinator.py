"""Coordinator state-reading unit tests (no running Home Assistant needed)."""

from datetime import timedelta
from types import SimpleNamespace

from homeassistant.util import dt as dt_util

from custom_components.pool_heating import const as C
from custom_components.pool_heating.coordinator import PoolHeatingCoordinator

_ENTITY = "sensor.pool"


def _stub(state, max_age_minutes=C.DEFAULT_POOL_TEMP_MAX_AGE):
    """Bare coordinator stand-in: just what _read_pool_temp touches."""
    return SimpleNamespace(
        hass=SimpleNamespace(
            states=SimpleNamespace(get=lambda eid: state if eid == _ENTITY else None)
        ),
        _cfg={C.CONF_POOL_TEMP_ENTITY: _ENTITY},
        _options=SimpleNamespace(pool_temp_max_age_minutes=max_age_minutes),
        _pool_temp_cache=None,
    )


def _state(value, age_minutes):
    reported = dt_util.utcnow() - timedelta(minutes=age_minutes)
    return SimpleNamespace(state=value, last_reported=reported, last_updated=reported)


def _read(stub):
    return PoolHeatingCoordinator._read_pool_temp(stub)


def test_fresh_reading_is_used():
    assert _read(_stub(_state("25.2", 1))) == 25.2


def test_sparse_thermometer_survives_between_reports():
    """A 45-minute-old report is still valid water temperature (inertia)."""
    assert _read(_stub(_state("25.2", 45))) == 25.2


def test_unavailable_flap_falls_back_to_cached_reading():
    stub = _stub(_state("25.2", 5))
    assert _read(stub) == 25.2
    stub.hass = SimpleNamespace(
        states=SimpleNamespace(get=lambda eid: _state("unavailable", 0))
    )
    assert _read(stub) == 25.2


def test_reading_older_than_max_age_is_fail_safe_none():
    assert _read(_stub(_state("25.2", C.DEFAULT_POOL_TEMP_MAX_AGE + 1))) is None


def test_max_age_option_is_respected():
    assert _read(_stub(_state("25.2", 45), max_age_minutes=30)) is None
    assert _read(_stub(_state("25.2", 45), max_age_minutes=60)) == 25.2


def test_never_seen_value_stays_none():
    assert _read(_stub(_state("unavailable", 0))) is None
    assert _read(_stub(None)) is None
