"""Recorder history access for fitting the thermal model.

All recorder queries are blocking DB calls and MUST run inside the recorder's
own DB executor (`get_instance(hass).async_add_executor_job`), never the generic
HA executor.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from functools import partial

from homeassistant.components.recorder import get_instance, history
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import HISTORY_LOOKBACK_DAYS
from .model import Sample, ThermoModel, Transition, fit_thermo
from .options import EngineOptions

_LOGGER = logging.getLogger(__name__)

_INVALID = (None, "unknown", "unavailable", "")


class HistoryReader:
    """Loads pool-temp / switch / outdoor history and fits the thermal model."""

    def __init__(
        self,
        hass: HomeAssistant,
        pool_entity: str,
        switch_entity: str,
        outdoor_entity: str | None,
        illuminance_entity: str | None = None,
    ) -> None:
        self._hass = hass
        self._pool = pool_entity
        self._switch = switch_entity
        self._outdoor = outdoor_entity
        self._illuminance = illuminance_entity

    async def async_fit_model(self, options: EngineOptions) -> ThermoModel:
        start = dt_util.utcnow() - timedelta(days=HISTORY_LOOKBACK_DAYS)
        entity_ids = [
            e for e in (self._pool, self._switch, self._outdoor, self._illuminance) if e
        ]
        states = await get_instance(self._hass).async_add_executor_job(
            self._load, start, entity_ids
        )
        pool = _to_samples(states.get(self._pool, []))
        switch = _to_transitions(states.get(self._switch, []))
        outdoor = (
            _to_samples(states.get(self._outdoor, [])) if self._outdoor else None
        )
        illuminance = (
            _to_samples(states.get(self._illuminance, [])) if self._illuminance else None
        )
        # The fit is pure CPU over potentially tens of thousands of samples —
        # keep it off the event loop.
        return await self._hass.async_add_executor_job(
            partial(fit_thermo, pool, switch, outdoor, options,
                    illuminance_series=illuminance)
        )

    def _load(self, start: datetime, entity_ids: list[str]) -> dict:
        """Blocking — runs in the recorder DB executor thread."""
        return history.get_significant_states(
            self._hass,
            start,
            None,
            entity_ids,
            significant_changes_only=False,  # need the dense curve, not just steps
            minimal_response=False,
            no_attributes=True,
        )


def _state_time(state: object) -> datetime | None:
    return getattr(state, "last_changed", None) or getattr(state, "last_updated", None)


def _to_samples(states: list) -> list[Sample]:
    out: list[Sample] = []
    for state in states:
        value = getattr(state, "state", None)
        when = _state_time(state)
        if value in _INVALID or when is None:
            continue
        try:
            out.append((when, float(value)))
        except (TypeError, ValueError):
            continue
    return out


def _to_transitions(states: list) -> list[Transition]:
    out: list[Transition] = []
    for state in states:
        value = getattr(state, "state", None)
        when = _state_time(state)
        if when is None:
            continue
        if value == "on":
            out.append((when, True))
        elif value == "off":
            out.append((when, False))
    return out
