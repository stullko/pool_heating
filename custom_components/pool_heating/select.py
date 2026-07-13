"""Select platform: operating mode override (auto / off / force_on)."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import MODES
from .entity import PoolHeatingEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([PoolHeatingModeSelect(entry.runtime_data, entry)])


class PoolHeatingModeSelect(PoolHeatingEntity, SelectEntity, RestoreEntity):
    """Lets the user pause automation or force heating."""

    _attr_translation_key = "mode"
    _attr_icon = "mdi:tune"
    _attr_options = list(MODES)

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "mode")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last and last.state in MODES and last.state != self.coordinator.mode:
            # Setup normally pre-restores the mode; this is the fallback path,
            # so re-decide promptly instead of waiting a full tick.
            self.coordinator.set_mode(last.state)
            await self.coordinator.async_request_refresh()

    @property
    def current_option(self) -> str:
        return self.coordinator.mode

    async def async_select_option(self, option: str) -> None:
        if option not in MODES:
            return
        self.coordinator.set_mode(option)
        await self.coordinator.async_request_refresh()
