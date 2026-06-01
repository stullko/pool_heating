"""Binary sensor platform: heating recommendation."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import PoolHeatingEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([ShouldHeatBinarySensor(entry.runtime_data, entry)])


class ShouldHeatBinarySensor(PoolHeatingEntity, BinarySensorEntity):
    """True when the engine wants the heat pump running right now."""

    _attr_translation_key = "should_heat"
    _attr_icon = "mdi:radiator"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "should_heat")

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.decision.should_heat

    @property
    def extra_state_attributes(self):
        return {"reason": self.coordinator.data.decision.reason_sk}
