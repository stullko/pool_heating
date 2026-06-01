"""Config flow tests (require Home Assistant test harness)."""

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from unittest.mock import patch  # noqa: E402

from homeassistant import config_entries  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.pool_heating import const as C  # noqa: E402

_BASE_INPUT = {
    C.CONF_NAME: "Pool",
    C.CONF_POOL_TEMP_ENTITY: "sensor.pool",
    C.CONF_HEAT_PUMP_SWITCH: "switch.hp",
    C.CONF_SHMU_STATION: 31479,
}


async def test_user_flow_creates_entry(hass, enable_custom_integrations):
    result = await hass.config_entries.flow.async_init(
        C.DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM

    with patch("custom_components.pool_heating.async_setup_entry", return_value=True):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], _BASE_INPUT
        )
    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["data"][C.CONF_HEAT_PUMP_SWITCH] == "switch.hp"


async def test_duplicate_station_aborts(hass, enable_custom_integrations):
    MockConfigEntry(domain=C.DOMAIN, unique_id="31479").add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        C.DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"], _BASE_INPUT
    )
    assert result2["type"] == FlowResultType.ABORT
