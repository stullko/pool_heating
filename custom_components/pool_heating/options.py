"""Typed engine options (pure) built from a config-entry options mapping.

Keeps the pure model/decision code free of Home Assistant config plumbing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from . import const as c


@dataclass(frozen=True)
class EngineOptions:
    target_temp: float
    hysteresis: float
    night_start: str
    night_end: str
    active_start: str
    active_end: str
    min_operating_outdoor_temp: float
    longterm_max_threshold: float
    cold_lookahead_days: int
    rain_mm_threshold: float
    rain_lookahead_h: int
    price_policy: str
    price_expensive_threshold: float
    catchup_deficit_c: float
    min_on_minutes: int
    min_off_minutes: int
    manage_filtration: bool
    frost_protect: bool
    frost_temp: float
    horizon_days: int
    rain_intensity_threshold: float
    pool_volume_l: float | None
    heat_pump_kw: float | None
    heat_pump_thermal_kw: float | None
    cop: float | None

    def effective_cop(self) -> float | None:
        """COP override, else thermal/electrical, else None."""
        if self.cop:
            return self.cop
        if self.heat_pump_kw and self.heat_pump_thermal_kw and self.heat_pump_kw > 0:
            return self.heat_pump_thermal_kw / self.heat_pump_kw
        return None


def _f(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _i(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _opt_f(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_options(options: Mapping[str, Any]) -> EngineOptions:
    """Build EngineOptions from a config-entry options mapping (with defaults)."""
    g = options.get
    return EngineOptions(
        target_temp=_f(g(c.CONF_TARGET_TEMP), c.DEFAULT_TARGET_TEMP),
        hysteresis=_f(g(c.CONF_HYSTERESIS), c.DEFAULT_HYSTERESIS),
        night_start=str(g(c.CONF_NIGHT_START, c.DEFAULT_NIGHT_START)),
        night_end=str(g(c.CONF_NIGHT_END, c.DEFAULT_NIGHT_END)),
        active_start=str(g(c.CONF_ACTIVE_START, c.DEFAULT_ACTIVE_START)),
        active_end=str(g(c.CONF_ACTIVE_END, c.DEFAULT_ACTIVE_END)),
        min_operating_outdoor_temp=_f(
            g(c.CONF_MIN_OPERATING_OUTDOOR_TEMP), c.DEFAULT_MIN_OPERATING_OUTDOOR_TEMP
        ),
        longterm_max_threshold=_f(
            g(c.CONF_LONGTERM_MAX_THRESHOLD), c.DEFAULT_LONGTERM_MAX_THRESHOLD
        ),
        cold_lookahead_days=_i(g(c.CONF_COLD_LOOKAHEAD_DAYS), c.DEFAULT_COLD_LOOKAHEAD_DAYS),
        rain_mm_threshold=_f(g(c.CONF_RAIN_MM_THRESHOLD), c.DEFAULT_RAIN_MM_THRESHOLD),
        rain_lookahead_h=_i(g(c.CONF_RAIN_LOOKAHEAD_H), c.DEFAULT_RAIN_LOOKAHEAD_H),
        price_policy=str(g(c.CONF_PRICE_POLICY, c.DEFAULT_PRICE_POLICY)),
        price_expensive_threshold=_f(
            g(c.CONF_PRICE_EXPENSIVE_THRESHOLD), c.DEFAULT_PRICE_EXPENSIVE_THRESHOLD
        ),
        catchup_deficit_c=_f(g(c.CONF_CATCHUP_DEFICIT_C), c.DEFAULT_CATCHUP_DEFICIT_C),
        min_on_minutes=_i(g(c.CONF_MIN_ON_MINUTES), c.DEFAULT_MIN_ON_MINUTES),
        min_off_minutes=_i(g(c.CONF_MIN_OFF_MINUTES), c.DEFAULT_MIN_OFF_MINUTES),
        manage_filtration=bool(g(c.CONF_MANAGE_FILTRATION, c.DEFAULT_MANAGE_FILTRATION)),
        frost_protect=bool(g(c.CONF_FROST_PROTECT, c.DEFAULT_FROST_PROTECT)),
        frost_temp=_f(g(c.CONF_FROST_TEMP), c.DEFAULT_FROST_TEMP),
        horizon_days=_i(g(c.CONF_HORIZON_DAYS), c.DEFAULT_HORIZON_DAYS),
        rain_intensity_threshold=_f(
            g(c.CONF_RAIN_INTENSITY_THRESHOLD), c.DEFAULT_RAIN_INTENSITY_THRESHOLD
        ),
        pool_volume_l=_opt_f(g(c.CONF_POOL_VOLUME_L)),
        heat_pump_kw=_f(g(c.CONF_HEAT_PUMP_KW), c.DEFAULT_HEAT_PUMP_KW),
        heat_pump_thermal_kw=_f(g(c.CONF_HEAT_PUMP_THERMAL_KW), c.DEFAULT_HEAT_PUMP_THERMAL_KW),
        cop=_opt_f(g(c.CONF_COP)),
    )
