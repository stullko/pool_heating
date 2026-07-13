"""Actuator safety-guard tests (require the Home Assistant test harness)."""

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from pytest_homeassistant_custom_component.common import async_mock_service  # noqa: E402

from custom_components.pool_heating import const as C  # noqa: E402
from custom_components.pool_heating.actuator import Actuator  # noqa: E402
from custom_components.pool_heating.decision import Decision  # noqa: E402
from custom_components.pool_heating.options import build_options  # noqa: E402


def _turn_on_decision() -> Decision:
    return Decision(
        should_heat=True,
        action=C.ACTION_TURN_ON,
        status=C.STATUS_HEATING,
        reason_sk="test",
    )


async def test_turn_on_calls_switch(hass):
    calls = async_mock_service(hass, "switch", "turn_on")
    hass.states.async_set("switch.hp", "off")
    actuator = Actuator(
        hass, "switch.hp", None, build_options({C.CONF_MIN_OFF_MINUTES: 0})
    )
    await actuator.async_apply(_turn_on_decision())
    assert [call.data["entity_id"] for call in calls] == ["switch.hp"]
    assert actuator.last_command is True


async def test_wont_start_pump_when_filtration_unavailable(hass):
    calls = async_mock_service(hass, "switch", "turn_on")
    hass.states.async_set("switch.hp", "off")
    hass.states.async_set("switch.filtration", "unavailable")
    opts = build_options({C.CONF_MIN_OFF_MINUTES: 0, C.CONF_MANAGE_FILTRATION: True})
    actuator = Actuator(hass, "switch.hp", "switch.filtration", opts)
    result = await actuator.async_apply(_turn_on_decision())
    assert calls == []
    assert actuator.last_command is None
    # the returned decision tells the truth instead of claiming "heating"
    assert result.status == C.STATUS_WAITING_FILTRATION
    assert result.should_heat is False


async def test_min_off_suppression_reports_compressor_protect(hass):
    calls = async_mock_service(hass, "switch", "turn_on")
    hass.states.async_set("switch.hp", "off")  # last_changed = now
    actuator = Actuator(hass, "switch.hp", None, build_options({}))  # min_off 10
    result = await actuator.async_apply(_turn_on_decision())
    assert calls == []
    assert result.status == C.STATUS_COMPRESSOR_PROTECT
    assert result.should_heat is True  # engine intent is preserved


async def test_min_on_suppression_reports_compressor_protect(hass):
    calls = async_mock_service(hass, "switch", "turn_off")
    hass.states.async_set("switch.hp", "on")  # last_changed = now
    actuator = Actuator(hass, "switch.hp", None, build_options({}))  # min_on 20
    decision = Decision(
        should_heat=False, action=C.ACTION_TURN_OFF,
        status=C.STATUS_WAITING_PRICE, reason_sk="test",
    )
    result = await actuator.async_apply(decision)
    assert calls == []
    assert result.status == C.STATUS_COMPRESSOR_PROTECT


async def test_guardrail_off_bypasses_min_on(hass):
    calls = async_mock_service(hass, "switch", "turn_off")
    hass.states.async_set("switch.hp", "on")
    actuator = Actuator(hass, "switch.hp", None, build_options({}))
    decision = Decision(
        should_heat=False, action=C.ACTION_TURN_OFF,
        status=C.STATUS_NIGHT_OFF, reason_sk="test",
    )
    result = await actuator.async_apply(decision)
    assert [call.data["entity_id"] for call in calls] == ["switch.hp"]
    assert result.status == C.STATUS_NIGHT_OFF


async def test_filtration_started_before_pump(hass):
    calls = async_mock_service(hass, "switch", "turn_on")
    hass.states.async_set("switch.hp", "off")
    hass.states.async_set("switch.filtration", "off")
    opts = build_options({C.CONF_MIN_OFF_MINUTES: 0, C.CONF_MANAGE_FILTRATION: True})
    actuator = Actuator(hass, "switch.hp", "switch.filtration", opts)
    await actuator.async_apply(_turn_on_decision())
    assert [call.data["entity_id"] for call in calls] == [
        "switch.filtration",
        "switch.hp",
    ]
