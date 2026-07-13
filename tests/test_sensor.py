"""Sensor-platform unit tests that don't need a running Home Assistant."""

from types import SimpleNamespace

from custom_components.pool_heating.sensor import PoolEnergyConsumedSensor


def _sensor(live_kwh: float) -> PoolEnergyConsumedSensor:
    coordinator = SimpleNamespace(
        data=SimpleNamespace(energy_consumed_kwh=live_kwh),
        seed_energy=lambda value: None,
    )
    entry = SimpleNamespace(entry_id="entry1", title="Pool")
    return PoolEnergyConsumedSensor(coordinator, entry)


def test_energy_never_dips_below_restored_value():
    """A dip after restart would count as a meter reset in HA statistics."""
    sensor = _sensor(0.0)  # coordinator data predates the restore seed
    sensor._restored = 12.4
    assert sensor.native_value == 12.4


def test_energy_follows_live_counter_once_ahead():
    sensor = _sensor(13.0)
    sensor._restored = 12.4
    assert sensor.native_value == 13.0
