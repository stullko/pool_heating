"""Applies a Decision to the heat-pump switch with safety guards.

Guards: idempotent service calls (only act on a real change), anti-short-cycle
(min on/off based on the switch's own last_changed), filtration prerequisite,
and never fighting an unavailable switch. Hard guardrail "off" reasons (night,
target, sensor loss, filtration off, mode off) may cut a short ON cycle.

`async_apply` returns the Decision that actually took effect: when a guard
suppresses the requested change, the returned decision carries a truthful
status (compressor_protect / waiting_filtration) instead of the engine's.
"""

from __future__ import annotations

import logging
import math
from dataclasses import replace

from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from . import const as c
from .decision import Decision
from .options import EngineOptions

_LOGGER = logging.getLogger(__name__)

SWITCH_DOMAIN = "switch"

# "Off" reasons that are allowed to interrupt the compressor min-on timer.
_GUARDRAIL_OFF = {
    c.STATUS_NIGHT_OFF,
    c.STATUS_TARGET_REACHED,
    c.STATUS_SENSOR_UNAVAILABLE,
    c.STATUS_MODE_OFF,
    c.STATUS_WAITING_FILTRATION,
}


class Actuator:
    """Drives the external heat-pump switch entity."""

    def __init__(
        self,
        hass: HomeAssistant,
        switch_entity: str,
        filtration_entity: str | None,
        options: EngineOptions,
    ) -> None:
        self._hass = hass
        self._switch = switch_entity
        self._filtration = filtration_entity
        self._options = options
        self._last_command: bool | None = None

    @property
    def last_command(self) -> bool | None:
        """The last on/off we actively commanded (None until we act)."""
        return self._last_command

    def update_options(self, options: EngineOptions) -> None:
        self._options = options

    async def async_apply(self, decision: Decision) -> Decision:
        """Drive the switch; return the decision that actually took effect."""
        if decision.action == c.ACTION_HOLD:
            return decision

        want_on = decision.action == c.ACTION_TURN_ON
        state = self._hass.states.get(self._switch)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            # Never fight an unknown/unavailable switch — and say so.
            return replace(
                decision, action=c.ACTION_HOLD, status=c.STATUS_SWITCH_UNAVAILABLE,
                reason_sk="Spínač tepelného čerpadla je nedostupný — čakám, kým sa ozve.",
                reason_en="Heat-pump switch unavailable",
            )

        current_on = state.state == STATE_ON
        elapsed_min = (dt_util.utcnow() - state.last_changed).total_seconds() / 60.0

        # Anti-short-cycle (optimisation-driven changes only).
        if (
            current_on and not want_on
            and elapsed_min < self._options.min_on_minutes
            and decision.status not in _GUARDRAIL_OFF
        ):
            left = math.ceil(self._options.min_on_minutes - elapsed_min)
            return replace(
                decision, action=c.ACTION_HOLD, status=c.STATUS_COMPRESSOR_PROTECT,
                reason_sk=(f"Ochrana kompresora: nechávam dobehnúť minimálny čas chodu "
                           f"({self._options.min_on_minutes} min, zostáva ~{left} min)."),
                reason_en="Compressor min-on protection",
            )
        if (
            not current_on and want_on
            and elapsed_min < self._options.min_off_minutes
            and decision.status != c.STATUS_FROST_PROTECT
        ):
            left = math.ceil(self._options.min_off_minutes - elapsed_min)
            return replace(
                decision, action=c.ACTION_HOLD, status=c.STATUS_COMPRESSOR_PROTECT,
                reason_sk=(f"Ochrana kompresora: pred štartom čakám minimálny čas "
                           f"vypnutia ({self._options.min_off_minutes} min, "
                           f"zostáva ~{left} min)."),
                reason_en="Compressor min-off protection",
            )

        if want_on and not await self._ensure_filtration_on():
            if decision.status == c.STATUS_FROST_PROTECT:
                # Freezing damage outweighs a possible dry run — proceed.
                _LOGGER.warning(
                    "Frost protection: starting heat pump %s despite unverified "
                    "filtration %s", self._switch, self._filtration,
                )
            elif current_on:
                # Pump is running without confirmed water flow — stop it now.
                _LOGGER.warning(
                    "Stopping heat pump %s: filtration %s is no longer confirmed",
                    self._switch, self._filtration,
                )
                await self._call_switch(False)
                return replace(
                    decision, should_heat=False, action=c.ACTION_TURN_OFF,
                    status=c.STATUS_WAITING_FILTRATION,
                    reason_sk=("Vypínam: filtrácia už nebeží alebo je nedostupná — "
                               "čerpadlo nesmie bežať bez prúdenia vody."),
                    reason_en="Filtration lost while heating",
                )
            else:
                _LOGGER.warning(
                    "Not starting heat pump %s: filtration %s is not confirmed running",
                    self._switch, self._filtration,
                )
                return replace(
                    decision, should_heat=False, action=c.ACTION_HOLD,
                    status=c.STATUS_WAITING_FILTRATION,
                    reason_sk=("Nehrejem: filtráciu sa nepodarilo zapnúť alebo je "
                               "nedostupná — čerpadlo bez prúdenia vody nespustím."),
                    reason_en="Filtration could not be ensured",
                )

        if current_on == want_on:
            self._last_command = want_on  # already in desired state; remember intent
            return decision

        if not await self._call_switch(want_on):
            return replace(
                decision, action=c.ACTION_HOLD, status=c.STATUS_SWITCH_UNAVAILABLE,
                reason_sk="Príkaz pre spínač čerpadla zlyhal — skúsim znova o chvíľu.",
                reason_en="Switch command failed",
            )
        _LOGGER.debug("Heat pump turned %s (%s)", "on" if want_on else "off",
                      decision.status)
        return decision

    async def _call_switch(self, want_on: bool) -> bool:
        service = SERVICE_TURN_ON if want_on else SERVICE_TURN_OFF
        try:
            await self._hass.services.async_call(
                SWITCH_DOMAIN, service, {ATTR_ENTITY_ID: self._switch}, blocking=True
            )
        except Exception as err:  # noqa: BLE001 - must not crash the update loop
            _LOGGER.warning("Failed to %s %s: %s", service, self._switch, err)
            return False
        self._last_command = want_on
        return True

    async def _ensure_filtration_on(self) -> bool:
        """Return True when water flow is assured.

        Checked whenever a filtration entity is configured — also in force_on
        mode and with manage_filtration off (then a provably OFF filtration
        refuses the start instead of being switched on).
        """
        if not self._filtration:
            return True
        state = self._hass.states.get(self._filtration)
        if state is not None and state.state == STATE_ON:
            return True
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return False  # cannot verify water flow -> never start the pump dry
        if not self._options.manage_filtration:
            return False  # filtration is off and we may not start it ourselves
        domain = self._filtration.split(".", 1)[0]
        try:
            await self._hass.services.async_call(
                domain, SERVICE_TURN_ON, {ATTR_ENTITY_ID: self._filtration}, blocking=True
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Failed to enable filtration %s: %s", self._filtration, err)
            return False
        # Confirm it actually switched on — a completed service call alone
        # does not prove water flow.
        fresh = self._hass.states.get(self._filtration)
        if fresh is not None and fresh.state == STATE_ON:
            _LOGGER.debug("Enabled filtration %s before heating", self._filtration)
            return True
        _LOGGER.warning(
            "Filtration %s did not report ON after turn_on", self._filtration
        )
        return False
