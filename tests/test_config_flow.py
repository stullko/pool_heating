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

_VALIDATE = (
    "custom_components.pool_heating.config_flow."
    "PoolHeatingConfigFlow._async_validate_station"
)


async def test_user_flow_creates_entry(hass, enable_custom_integrations):
    result = await hass.config_entries.flow.async_init(
        C.DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM

    with (
        patch(_VALIDATE, return_value=None),
        patch("custom_components.pool_heating.async_setup_entry", return_value=True),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], _BASE_INPUT
        )
    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["data"][C.CONF_HEAT_PUMP_SWITCH] == "switch.hp"


async def test_duplicate_heat_pump_switch_aborts(hass, enable_custom_integrations):
    MockConfigEntry(domain=C.DOMAIN, unique_id="switch.hp").add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        C.DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(_VALIDATE, return_value=None):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], _BASE_INPUT
        )
    assert result2["type"] == FlowResultType.ABORT


async def test_two_pools_may_share_a_station(hass, enable_custom_integrations):
    MockConfigEntry(domain=C.DOMAIN, unique_id="switch.other_hp").add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        C.DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with (
        patch(_VALIDATE, return_value=None),
        patch("custom_components.pool_heating.async_setup_entry", return_value=True),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], _BASE_INPUT
        )
    assert result2["type"] == FlowResultType.CREATE_ENTRY


async def test_same_switch_in_legacy_entry_aborts(hass, enable_custom_integrations):
    """Entries created before 0.2.0 still carry a station-based unique_id."""
    MockConfigEntry(
        domain=C.DOMAIN,
        unique_id="31479",
        data={C.CONF_HEAT_PUMP_SWITCH: "switch.hp"},
    ).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        C.DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(_VALIDATE, return_value=None):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], _BASE_INPUT
        )
    assert result2["type"] == FlowResultType.ABORT


async def test_unusable_station_shows_field_error(hass, enable_custom_integrations):
    result = await hass.config_entries.flow.async_init(
        C.DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(_VALIDATE, return_value="invalid_station"):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], _BASE_INPUT
        )
    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {C.CONF_SHMU_STATION: "invalid_station"}


_ENTRY_DATA = {
    **_BASE_INPUT,
    C.CONF_OUTDOOR_TEMP_ENTITY: "sensor.outdoor",
}


def _add_entry(hass, **overrides):
    data = {**_ENTRY_DATA, **overrides}
    entry = MockConfigEntry(
        domain=C.DOMAIN,
        unique_id=data[C.CONF_HEAT_PUMP_SWITCH],
        data=data,
        title=data[C.CONF_NAME],
    )
    entry.add_to_hass(hass)
    return entry


async def _reconfigure(hass, entry, user_input):
    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    with (
        patch(_VALIDATE, return_value=None),
        patch("custom_components.pool_heating.async_setup_entry", return_value=True),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input
        )
        await hass.async_block_till_done()
    return result2


async def test_reconfigure_repoints_pool_temp_sensor(hass, enable_custom_integrations):
    """The wiring — the broken pool sensor above all — is fixable in the UI."""
    entry = _add_entry(hass)
    result = await _reconfigure(
        hass, entry, {**_ENTRY_DATA, C.CONF_POOL_TEMP_ENTITY: "sensor.pool_new"}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[C.CONF_POOL_TEMP_ENTITY] == "sensor.pool_new"
    assert len(hass.config_entries.async_entries(C.DOMAIN)) == 1


async def test_reconfigure_clears_omitted_optional_entity(
    hass, enable_custom_integrations
):
    """Leaving an optional selector empty removes it from the entry data."""
    entry = _add_entry(hass)
    new_input = {k: v for k, v in _ENTRY_DATA.items() if k != C.CONF_OUTDOOR_TEMP_ENTITY}
    result = await _reconfigure(hass, entry, new_input)
    assert result["reason"] == "reconfigure_successful"
    assert C.CONF_OUTDOOR_TEMP_ENTITY not in entry.data


async def test_reconfigure_switch_change_updates_unique_id(
    hass, enable_custom_integrations
):
    entry = _add_entry(hass)
    result = await _reconfigure(
        hass, entry, {**_ENTRY_DATA, C.CONF_HEAT_PUMP_SWITCH: "switch.hp2"}
    )
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[C.CONF_HEAT_PUMP_SWITCH] == "switch.hp2"
    assert entry.unique_id == "switch.hp2"


async def test_reconfigure_rejects_switch_of_other_entry(
    hass, enable_custom_integrations
):
    entry = _add_entry(hass)
    _add_entry(hass, **{C.CONF_HEAT_PUMP_SWITCH: "switch.other", C.CONF_NAME: "Other"})
    result = await _reconfigure(
        hass, entry, {**_ENTRY_DATA, C.CONF_HEAT_PUMP_SWITCH: "switch.other"}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[C.CONF_HEAT_PUMP_SWITCH] == "switch.hp"


async def test_reconfigure_bad_station_shows_field_error(
    hass, enable_custom_integrations
):
    entry = _add_entry(hass)
    result = await entry.start_reconfigure_flow(hass)
    with patch(_VALIDATE, return_value="invalid_station"):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], dict(_ENTRY_DATA)
        )
    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {C.CONF_SHMU_STATION: "invalid_station"}
    assert entry.data[C.CONF_POOL_TEMP_ENTITY] == "sensor.pool"
