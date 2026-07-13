"""The Pool Heating Controller integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import restore_state
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import const as c
from .options import build_options

_LOGGER = logging.getLogger(__name__)


def _restored_mode(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    """Best-effort read of the mode select's saved state before entities exist.

    The coordinator's first refresh runs before the select entity restores
    itself; without this, a restart briefly reverts a user's off/force_on to
    auto and can pulse the pump.
    """
    try:
        entity_id = er.async_get(hass).async_get_entity_id(
            "select", c.DOMAIN, f"{entry.entry_id}_mode"
        )
        if not entity_id:
            return None
        stored = restore_state.async_get(hass).last_states.get(entity_id)
        if stored and stored.state and stored.state.state in c.MODES:
            return stored.state.state
    except Exception:  # noqa: BLE001 - restore is opportunistic, never fatal
        _LOGGER.debug("Could not pre-restore mode", exc_info=True)
    return None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Pool Heating Controller from a config entry."""
    from zoneinfo import ZoneInfo

    from .actuator import Actuator
    from .coordinator import PoolHeatingCoordinator
    from .history import HistoryReader
    from .shmu import ShmuClient
    from .util import set_local_tz

    try:
        set_local_tz(ZoneInfo(hass.config.time_zone))
    except Exception:  # noqa: BLE001 - fall back to the packaged default zone
        _LOGGER.debug("Unusable HA timezone %r, keeping default", hass.config.time_zone)

    session = async_get_clientsession(hass)
    options = build_options(entry.options)
    station = int(entry.data.get(c.CONF_SHMU_STATION, c.DEFAULT_SHMU_STATION))

    client = ShmuClient(session, station)
    history_reader = HistoryReader(
        hass,
        entry.data[c.CONF_POOL_TEMP_ENTITY],
        entry.data[c.CONF_HEAT_PUMP_SWITCH],
        entry.data.get(c.CONF_OUTDOOR_TEMP_ENTITY),
        entry.data.get(c.CONF_ILLUMINANCE_ENTITY),
    )
    actuator = Actuator(
        hass,
        entry.data[c.CONF_HEAT_PUMP_SWITCH],
        entry.data.get(c.CONF_FILTRATION_ENTITY),
        options,
    )
    coordinator = PoolHeatingCoordinator(hass, entry, client, history_reader, actuator)
    if (mode := _restored_mode(hass, entry)) is not None:
        coordinator.set_mode(mode)
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


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Purge the persisted learned model when the entry is deleted."""
    from homeassistant.helpers.storage import Store

    from .coordinator import STORAGE_VERSION, storage_key

    await Store(hass, STORAGE_VERSION, storage_key(entry.entry_id)).async_remove()
