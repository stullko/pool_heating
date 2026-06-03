"""Shared base entity for Pool Heating Controller."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DEFAULT_NAME
from .coordinator import PoolHeatingCoordinator


class PoolHeatingEntity(CoordinatorEntity[PoolHeatingCoordinator]):
    """Base entity binding to the coordinator and the logical device."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: PoolHeatingCoordinator, entry: ConfigEntry, key: str
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title or DEFAULT_NAME,
            manufacturer="SHMU + local",
            model="Pool heating controller",
        )
