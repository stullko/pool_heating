"""Coordinator: reads state, drives the model + decision engine, acts.

Three cadences share one coordinator:
  * decision tick   — every DECISION_INTERVAL (cheap: read states, decide, act)
  * forecast fetch  — throttled to FORECAST_REFRESH (HTTP)
  * model refit     — throttled to MODEL_REFIT (recorder DB)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import const as c
from .actuator import Actuator
from .decision import Decision, DecisionInputs, decide
from .forecast import NormalizedForecast
from .history import HistoryReader
from .model import ThermoModel
from .options import EngineOptions, build_options
from .shmu import ShmuClient, ShmuError

_LOGGER = logging.getLogger(__name__)

_INVALID = (None, "unknown", "unavailable", "")


@dataclass
class PoolHeatingData:
    """Everything the entities render — produced once per tick."""

    decision: Decision
    pool_temp: float | None
    outdoor_temp: float | None
    target_temp: float
    model: ThermoModel
    forecast_run_id: str | None
    forecast_generated_at: datetime | None
    forecast_available: bool
    switch_is_on: bool | None
    mode: str
    available: bool
    energy_consumed_kwh: float
    power_w: float
    rain_intensity: float | None
    illuminance: float | None


class PoolHeatingCoordinator(DataUpdateCoordinator[PoolHeatingData]):
    """Owns the control loop for one configured pool."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: ShmuClient,
        history_reader: HistoryReader,
        actuator: Actuator,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=c.DOMAIN,
            config_entry=entry,
            update_interval=c.DECISION_INTERVAL,
            always_update=True,
        )
        self._entry = entry
        self._client = client
        self._history = history_reader
        self._actuator = actuator
        self._cfg = dict(entry.data)
        self._options: EngineOptions = build_options(entry.options)

        self._forecast: NormalizedForecast | None = None
        self._forecast_at: datetime | None = None
        self._model: ThermoModel | None = None
        self._model_at: datetime | None = None
        self._mode: str = c.DEFAULT_MODE
        self._energy_kwh: float = 0.0
        self._last_energy_tick: datetime | None = None

    # ---- mode override (set by the select entity) -------------------------
    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        self._mode = mode

    def seed_energy(self, value: float) -> None:
        """Restore the cumulative consumed-energy counter after a restart."""
        if value and value > self._energy_kwh:
            self._energy_kwh = value

    # ---- main loop --------------------------------------------------------
    async def _async_update_data(self) -> PoolHeatingData:
        now = dt_util.utcnow()

        await self._maybe_refresh_forecast(now)
        await self._maybe_refit_model(now)
        model = self._model or ThermoModel.default(self._options)

        pool = self._read_float(self._cfg.get(c.CONF_POOL_TEMP_ENTITY), c.SENSOR_MAX_AGE)
        outdoor = self._read_float(self._cfg.get(c.CONF_OUTDOOR_TEMP_ENTITY))
        if outdoor is None and self._forecast is not None:
            outdoor = self._forecast.current_temp

        switch_is_on = self._read_onoff(self._cfg.get(c.CONF_HEAT_PUMP_SWITCH))
        filtration_on = self._read_onoff(self._cfg.get(c.CONF_FILTRATION_ENTITY))
        expensive = self._read_onoff(self._cfg.get(c.CONF_ELECTRICITY_EXPENSIVE_ENTITY))
        day_on = self._read_onoff(self._cfg.get(c.CONF_DAY_ENTITY))
        rain_intensity = self._read_float(self._cfg.get(c.CONF_RAIN_INTENSITY_ENTITY))
        illuminance = self._read_float(self._cfg.get(c.CONF_ILLUMINANCE_ENTITY))

        # Accumulate consumed electrical energy from heat-pump ON runtime.
        electrical_kw = self._options.heat_pump_kw or 0.0
        if self._last_energy_tick is not None and switch_is_on:
            hours = (now - self._last_energy_tick).total_seconds() / 3600.0
            self._energy_kwh += electrical_kw * hours
        self._last_energy_tick = now

        manual = (
            self._mode == c.MODE_AUTO
            and self._actuator.last_command is not None
            and switch_is_on is not None
            and switch_is_on != self._actuator.last_command
        )

        decision = decide(
            DecisionInputs(
                now=now,
                pool_temp=pool,
                outdoor_temp=outdoor,
                forecast=self._forecast,
                model=model,
                options=self._options,
                mode=self._mode,
                filtration_on=filtration_on,
                electricity_expensive=expensive,
                day_on=day_on,
                switch_is_on=switch_is_on,
                manual_override=manual,
                rain_intensity=rain_intensity,
                illuminance=illuminance,
            )
        )

        await self._actuator.async_apply(decision)

        return PoolHeatingData(
            decision=decision,
            pool_temp=pool,
            outdoor_temp=outdoor,
            target_temp=self._options.target_temp,
            model=model,
            forecast_run_id=self._forecast.run_id if self._forecast else None,
            forecast_generated_at=self._forecast.generated_at if self._forecast else None,
            forecast_available=self._forecast is not None,
            switch_is_on=switch_is_on,
            mode=self._mode,
            available=pool is not None,
            energy_consumed_kwh=round(self._energy_kwh, 3),
            power_w=round(electrical_kw * 1000.0, 0) if switch_is_on else 0.0,
            rain_intensity=rain_intensity,
            illuminance=illuminance,
        )

    async def _maybe_refresh_forecast(self, now: datetime) -> None:
        if self._forecast is not None and self._forecast_at is not None and (
            now - self._forecast_at < c.FORECAST_REFRESH
        ):
            return
        try:
            self._forecast = await self._client.async_get_forecast()
            self._forecast_at = now
        except ShmuError as err:
            if self._forecast is None:
                _LOGGER.warning("SHMU forecast unavailable: %s", err)
            else:
                _LOGGER.warning(
                    "SHMU refresh failed, using cached run %s: %s",
                    self._forecast.run_id, err,
                )

    async def _maybe_refit_model(self, now: datetime) -> None:
        if self._model is not None and self._model_at is not None and (
            now - self._model_at < c.MODEL_REFIT
        ):
            return
        try:
            self._model = await self._history.async_fit_model(self._options)
            self._model_at = now
        except Exception as err:  # noqa: BLE001 - history must never kill the loop
            _LOGGER.warning("Thermal model refit failed: %s", err)
            if self._model is None:
                self._model = ThermoModel.default(self._options)

    # ---- state helpers ----------------------------------------------------
    def _read_float(self, entity_id: str | None, max_age=None) -> float | None:
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in _INVALID:
            return None
        if max_age is not None and (dt_util.utcnow() - state.last_updated) > max_age:
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

    def _read_onoff(self, entity_id: str | None) -> bool | None:
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in _INVALID:
            return None
        return state.state == "on"
