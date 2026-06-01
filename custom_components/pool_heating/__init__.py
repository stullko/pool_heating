"""The Pool Heating Controller integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import const as c
from .actuator import Actuator
from .coordinator import PoolHeatingCoordinator
from .history import HistoryReader
from .options import build_options
from .shmu import ShmuClient

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Pool Heating Controller from a config entry."""
    session = async_get_clientsession(hass)
    options = build_options(entry.options)
    station = int(entry.data.get(c.CONF_SHMU_STATION, c.DEFAULT_SHMU_STATION))

    client = ShmuClient(session, station)
    history_reader = HistoryReader(
        hass,
        entry.data[c.CONF_POOL_TEMP_ENTITY],
        entry.data[c.CONF_HEAT_PUMP_SWITCH],
        entry.data.get(c.CONF_OUTDOOR_TEMP_ENTITY),
    )
    actuator = Actuator(
        hass,
        entry.data[c.CONF_HEAT_PUMP_SWITCH],
        entry.data.get(c.CONF_FILTRATION_ENTITY),
        options,
    )
    coordinator = PoolHeatingCoordinator(hass, entry, client, history_reader, actuator)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, c.PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, c.PLATFORMS)
