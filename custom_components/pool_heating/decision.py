"""Pure deterministic decision engine (no Home Assistant imports).

Given the current state, forecast and learned model, produce a single
`Decision` (turn the heat-pump switch on/off/leave-alone) plus an explainable
Slovak status. Ordered: hard guardrails first, optimisation last.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import const as c
from .forecast import NormalizedForecast
from .model import Projection, ThermoModel, project
from .options import EngineOptions
from .util import is_active_hour, is_night, to_local

UTC = timezone.utc

WEEKDAYS_SK = [
    "pondelok", "utorok", "streda", "štvrtok", "piatok", "sobota", "nedeľa",
]


@dataclass
class DecisionInputs:
    now: datetime
    pool_temp: float | None
    outdoor_temp: float | None
    forecast: NormalizedForecast | None
    model: ThermoModel
    options: EngineOptions
    mode: str = c.MODE_AUTO
    filtration_on: bool | None = None       # None => not configured or unavailable
    filtration_configured: bool = False
    electricity_expensive: bool | None = None
    electricity_price: float | None = None  # EUR/kWh, informational
    day_on: bool | None = None
    switch_is_on: bool | None = None
    manual_override: bool = False
    rain_intensity: float | None = None
    illuminance: float | None = None


@dataclass
class Decision:
    should_heat: bool
    action: str                      # ACTION_TURN_ON / ACTION_TURN_OFF / ACTION_HOLD
    status: str
    reason_sk: str
    reason_en: str = ""
    wait_until: datetime | None = None
    predicted_ready: datetime | None = None
    required_hours: float | None = None
    energy_kwh: float | None = None
    energy_cost_eur: float | None = None
    next_window: datetime | None = None
    trajectory: list[tuple[datetime, float]] = field(default_factory=list)


def decide(inp: DecisionInputs) -> Decision:
    """Run the full ordered decision pipeline."""
    o = inp.options
    now = inp.now.astimezone(UTC)

    # Projection (predicted ready) — attached to most statuses for the UI.
    proj = (
        project(inp.pool_temp, inp.model, inp.forecast, o, now)
        if inp.forecast is not None and inp.pool_temp is not None
        else Projection(None, 0.0, None, [])
    )

    cost = (
        round(proj.energy_kwh * inp.electricity_price, 2)
        if proj.energy_kwh is not None and inp.electricity_price is not None
        else None
    )

    def out(should_heat, action, status, reason_sk, reason_en="", **kw):
        return Decision(
            should_heat=should_heat, action=action, status=status,
            reason_sk=reason_sk, reason_en=reason_en,
            predicted_ready=proj.predicted_ready,
            required_hours=round(proj.required_hours, 1) if proj.required_hours else None,
            energy_kwh=proj.energy_kwh,
            energy_cost_eur=cost,
            trajectory=proj.trajectory,
            **kw,
        )

    # 0. Operating mode override --------------------------------------------
    if inp.mode == c.MODE_OFF:
        return out(False, c.ACTION_TURN_OFF, c.STATUS_MODE_OFF,
                   "Režim: vypnuté. Automatika je pozastavená.", "Mode: off")
    if inp.mode == c.MODE_FORCE_ON:
        return out(True, c.ACTION_TURN_ON, c.STATUS_HEATING,
                   "Vynútené kúrenie (manuálny režim).", "Mode: force-on")

    # 1. Pool sensor validity (fail-safe: never heat blind) -----------------
    if inp.pool_temp is None:
        return out(False, c.ACTION_TURN_OFF, c.STATUS_SENSOR_UNAVAILABLE,
                   "Pozastavené: teplota vody je nedostupná, pre istotu nehrejem.",
                   "Pool sensor unavailable")

    pool = inp.pool_temp
    amb_now = inp.outdoor_temp
    if amb_now is None and inp.forecast is not None:
        amb_now = inp.forecast.current_temp

    # 2. Manual override (user flipped the switch) --------------------------
    if inp.manual_override:
        state_sk = "zapnuté" if inp.switch_is_on else "vypnuté"
        return out(bool(inp.switch_is_on), c.ACTION_HOLD, c.STATUS_MANUAL_OVERRIDE,
                   f"Manuálny režim: rešpektujem ručné {state_sk}. Automatika pozastavená.",
                   "Manual override")

    # 3. Filtration explicitly off (pump needs water flow) ------------------
    if inp.filtration_on is False and not o.manage_filtration:
        return out(False, c.ACTION_TURN_OFF, c.STATUS_WAITING_FILTRATION,
                   "Nehrejem: filtrácia je vypnutá — čerpadlo potrebuje prúdenie vody.",
                   "Filtration off")

    # 4. Frost protection (safety, overrides night and an *unknown*
    #    filtration state — freezing damage outweighs a possible dry run) ---
    if o.frost_protect and pool <= o.frost_temp:
        return out(True, c.ACTION_TURN_ON, c.STATUS_FROST_PROTECT,
                   f"Hrejem (ochrana pred mrazom): voda {_t(pool)} °C.",
                   "Frost protection")

    # 4b. Filtration state unknown (fail safe for normal operation) ---------
    if inp.filtration_configured and inp.filtration_on is None:
        return out(False, c.ACTION_TURN_OFF, c.STATUS_WAITING_FILTRATION,
                   "Nehrejem: stav filtrácie je nedostupný — bez overeného prúdenia "
                   "vody čerpadlo nespúšťam.", "Filtration state unavailable")

    # 5. Night / outside active window --------------------------------------
    if (
        is_night(now, o.night_start, o.night_end)
        or not is_active_hour(now, o.active_start, o.active_end)
        or inp.day_on is False
    ):
        return out(False, c.ACTION_TURN_OFF, c.STATUS_NIGHT_OFF,
                   f"Nehrejem: nočný režim / mimo okna {o.active_start[:5]}–{o.active_end[:5]}. "
                   "Pokračujem cez deň.", "Night / outside window")

    # 6. Target reached (+ hysteresis band) ---------------------------------
    if pool >= o.target_temp:
        return out(False, c.ACTION_TURN_OFF, c.STATUS_TARGET_REACHED,
                   f"Cieľ dosiahnutý: voda {_t(pool)} °C (cieľ {_t(o.target_temp)} °C). "
                   "Udržiavam, nehrejem.", "Target reached")
    on_threshold = o.target_temp - o.hysteresis
    if pool > on_threshold and not inp.switch_is_on:
        return out(False, c.ACTION_TURN_OFF, c.STATUS_IDLE_BAND,
                   f"Nehrejem: {_t(pool)} °C je tesne pod cieľom "
                   f"(spínam až pod {_t(on_threshold)} °C).", "Idle hysteresis band")

    # 6b. Live rain right now (real rain sensor) — strong, forecast-independent
    if inp.rain_intensity is not None and inp.rain_intensity > o.rain_intensity_threshold:
        return out(False, c.ACTION_TURN_OFF, c.STATUS_WAITING_RAIN,
                   f"Nehrejem: prší práve teraz (intenzita {_t(inp.rain_intensity)}). Počkám.",
                   "Live rain now")

    # 7. Forecast unavailable (degraded: conservative, do not heat) ---------
    if inp.forecast is None:
        return out(False, c.ACTION_TURN_OFF, c.STATUS_FORECAST_UNAVAILABLE,
                   "Nehrejem opatrne: predpoveď je nedostupná, skúšam obnoviť dáta.",
                   "Forecast unavailable")
    fc = inp.forecast

    # 8. Outdoor too cold right now (air-source efficiency) -----------------
    if amb_now is not None and amb_now < o.min_operating_outdoor_temp:
        return out(False, c.ACTION_TURN_OFF, c.STATUS_WAITING_COLD_NOW,
                   f"Nehrejem: vonku len {_t(amb_now)} °C "
                   f"(TČ efektívne od {_t(o.min_operating_outdoor_temp)} °C).",
                   "Outdoor too cold now")

    # 9. Rain imminent ------------------------------------------------------
    if fc.rain_within(now, o.rain_lookahead_h, o.rain_mm_threshold):
        win = _next_window(fc, now, o)
        mm = fc.precip_sum(now, now + timedelta(hours=o.rain_lookahead_h))
        return out(False, c.ACTION_TURN_OFF, c.STATUS_WAITING_RAIN,
                   f"Nehrejem: v najbližších {o.rain_lookahead_h} h dážď ~{_t(mm)} mm. "
                   f"Vhodné okno od {dt_sk(win)}, dohriatie cca {dt_sk(proj.predicted_ready)}.",
                   "Rain imminent", wait_until=win, next_window=win)

    # 10. Long-term cold spell ----------------------------------------------
    if fc.daymax_below(now, o.longterm_max_threshold, o.cold_lookahead_days):
        win = _next_window(fc, now, o)
        best = _best_daymax(fc, now, o.horizon_days)
        return out(False, c.ACTION_TURN_OFF, c.STATUS_WAITING_COLD,
                   f"Nehrejem: dlhodobo max do {_t(best)} °C (pod {_t(o.longterm_max_threshold)} °C), "
                   f"neoplatí sa. Najbližšie vhodné okno: {dt_sk(win)}.",
                   "Long-term cold", wait_until=win, next_window=win)

    # 11. Productivity / window check ---------------------------------------
    win = _next_window(fc, now, o)
    if amb_now is not None:
        solar_now = 0.0
        if inp.illuminance is not None:
            solar_now = inp.model.solar * _clamp01(inp.illuminance / c.FULL_SUN_LUX)
        gain_now = (
            inp.model.heat_rate_at(amb_now)
            - inp.model.loss_rate_at(o.target_temp, amb_now)
            + solar_now
        )
        if gain_now < c.G_MIN_C_PER_H:
            if win is not None:
                return out(False, c.ACTION_TURN_OFF, c.STATUS_WAITING_BETTER_WINDOW,
                           f"Nehrejem teraz: počkám na výhodnejšie okno od {dt_sk(win)} "
                           "(teplejšie/slnečnejšie).", "Wait for better window",
                           wait_until=win, next_window=win)
            return out(False, c.ACTION_TURN_OFF, c.STATUS_NO_WINDOW,
                       f"Nehrejem: v najbližších {o.horizon_days} dňoch nie sú vhodné podmienky "
                       f"(max {_t(_best_daymax(fc, now, o.horizon_days))} °C). Sledujem predpoveď.",
                       "No window in horizon", next_window=None)

    # 12. Electricity price layer (cheap preferred + catch-up) --------------
    if inp.electricity_expensive and o.price_policy != c.PRICE_POLICY_IGNORE:
        deficit = o.target_temp - pool
        if o.price_policy == c.PRICE_POLICY_CHEAP_ONLY or deficit < o.catchup_deficit_c:
            price_sk = (
                f" Aktuálna cena {inp.electricity_price:.2f} €/kWh."
                if inp.electricity_price is not None else ""
            )
            return out(False, c.ACTION_TURN_OFF, c.STATUS_WAITING_PRICE,
                       "Nehrejem: elektrina je teraz drahá, počasie je vhodné — "
                       f"čakám na lacnejšiu hodinu.{price_sk}", "Waiting for cheaper price",
                       next_window=win)
        # cheap_preferred + big deficit => catch up even though it's expensive

    # 13. Heat now ----------------------------------------------------------
    rate = inp.model.heat_rate_at(amb_now) if amb_now is not None else inp.model.r_a
    base = (
        f"Hrejem: voda {_t(pool)} °C → cieľ {_t(o.target_temp)} °C, tempo ~{_t(rate)} °C/h. "
        f"Odhad dohriatia {dt_sk(proj.predicted_ready)}."
    )
    if inp.model.learning:
        base += " (orientačne — učím sa správanie bazéna.)"
    return out(True, c.ACTION_TURN_ON, c.STATUS_HEATING, base, "Heating", next_window=win)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _next_window(fc: NormalizedForecast, now: datetime, o: EngineOptions) -> datetime | None:
    return fc.next_warm_window(
        now,
        min_temp=o.min_operating_outdoor_temp,
        daily_max_threshold=o.longterm_max_threshold,
        rain_mm=o.rain_mm_threshold,
        rain_window_h=o.rain_lookahead_h,
        active_start=o.active_start,
        active_end=o.active_end,
    )


def _best_daymax(fc: NormalizedForecast, now: datetime, horizon_days: int) -> float:
    today = to_local(now).date()
    highs = [
        d.temp_max for d in fc.daily
        if d.temp_max is not None and today <= d.day
    ][:horizon_days]
    return max(highs) if highs else 0.0


def dt_sk(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    local = to_local(dt)
    return f"{WEEKDAYS_SK[local.weekday()]} {local.strftime('%H:%M')}"


def _t(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}"


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))
