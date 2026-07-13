"""Sensor platform: status (with reason) + derived diagnostics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EntityCategory,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ALL_STATUSES
from .coordinator import PoolHeatingData
from .entity import PoolHeatingEntity


@dataclass(frozen=True, kw_only=True)
class PoolSensorDescription(SensorEntityDescription):
    value_fn: Callable[[PoolHeatingData], Any]
    attrs_fn: Callable[[PoolHeatingData], dict[str, Any]] | None = None


def _status_attrs(d: PoolHeatingData) -> dict[str, Any]:
    dec = d.decision
    return {
        "reason": dec.reason_sk,
        "reason_en": dec.reason_en,
        "should_heat": dec.should_heat,
        "action": dec.action,
        "predicted_ready": dec.predicted_ready.isoformat() if dec.predicted_ready else None,
        "next_window": dec.next_window.isoformat() if dec.next_window else None,
        "wait_until": dec.wait_until.isoformat() if dec.wait_until else None,
        "required_heating_hours": dec.required_hours,
        "energy_needed_kwh": dec.energy_kwh,
        "estimated_cost_eur": dec.energy_cost_eur,
        "electricity_price": d.electricity_price,
        "mode": d.mode,
        "pool_temp": d.pool_temp,
        "outdoor_temp": d.outdoor_temp,
        "target_temp": d.target_temp,
        "model_confidence": round(d.model.confidence * 100, 1),
        "learning": d.model.learning,
        "loss_coefficient_per_h": d.model.k,
        "forecast_run_id": d.forecast_run_id,
        "forecast_available": d.forecast_available,
    }


def _heat_rate(d: PoolHeatingData) -> float:
    amb = d.outdoor_temp if d.outdoor_temp is not None else 20.0
    return round(d.model.heat_rate_at(amb), 3)


def _prediction_attrs(d: PoolHeatingData) -> dict[str, Any]:
    """Projected temperature trajectory for graphing (e.g. apexcharts-card)."""
    return {
        "target_temp": d.target_temp,
        "forecast": [
            {"datetime": when.isoformat(), "temperature": temp}
            for when, temp in d.decision.trajectory
        ],
    }


SENSORS: tuple[PoolSensorDescription, ...] = (
    PoolSensorDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=list(ALL_STATUSES),
        icon="mdi:pool",
        value_fn=lambda d: d.decision.status,
        attrs_fn=_status_attrs,
    ),
    PoolSensorDescription(
        key="predicted_ready",
        translation_key="predicted_ready",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:calendar-clock",
        value_fn=lambda d: d.decision.predicted_ready,
        attrs_fn=_prediction_attrs,
    ),
    PoolSensorDescription(
        key="required_heating_hours",
        translation_key="required_heating_hours",
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:timer-sand",
        value_fn=lambda d: d.decision.required_hours,
    ),
    PoolSensorDescription(
        key="energy_needed",
        translation_key="energy_needed",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:lightning-bolt",
        value_fn=lambda d: d.decision.energy_kwh,
    ),
    PoolSensorDescription(
        key="power",
        translation_key="power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:flash",
        value_fn=lambda d: d.power_w,
    ),
    PoolSensorDescription(
        key="heat_rate",
        translation_key="heat_rate",
        native_unit_of_measurement="°C/h",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:thermometer-chevron-up",
        value_fn=_heat_rate,
    ),
    PoolSensorDescription(
        key="loss_coefficient",
        translation_key="loss_coefficient",
        native_unit_of_measurement="1/h",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:thermometer-chevron-down",
        value_fn=lambda d: d.model.k,
    ),
    PoolSensorDescription(
        key="model_confidence",
        translation_key="model_confidence",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:school",
        value_fn=lambda d: round(d.model.confidence * 100, 1),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        PoolHeatingSensor(coordinator, entry, desc) for desc in SENSORS
    ]
    entities.append(PoolEnergyConsumedSensor(coordinator, entry))
    async_add_entities(entities)


class PoolHeatingSensor(PoolHeatingEntity, SensorEntity):
    """A sensor backed by a PoolSensorDescription value function."""

    entity_description: PoolSensorDescription
    # The projected trajectory changes every tick and would bloat the
    # recorder database — keep it out of recorded history.
    _unrecorded_attributes = frozenset({"forecast"})

    def __init__(self, coordinator, entry, description: PoolSensorDescription) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self):
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data)


class PoolEnergyConsumedSensor(PoolHeatingEntity, RestoreSensor):
    """Cumulative electrical energy consumed by the heat pump (ON runtime x kW)."""

    _attr_translation_key = "energy_consumed"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:lightning-bolt-circle"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "energy_consumed")
        self._restored = 0.0

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_sensor_data()
        if last and last.native_value is not None:
            try:
                self._restored = float(last.native_value)
            except (TypeError, ValueError):
                return
            self.coordinator.seed_energy(self._restored)

    @property
    def native_value(self) -> float:
        # coordinator.data may predate the restore seed; never report a dip —
        # a TOTAL_INCREASING drop would register as a meter reset in statistics.
        return max(self.coordinator.data.energy_consumed_kwh, self._restored)
