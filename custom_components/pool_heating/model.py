"""Pure thermodynamic model (no Home Assistant imports).

Two learned behaviours, fitted from recorder history:
  * loss coefficient k (Newton cooling) from pump-OFF intervals
  * net heat-up rate r_net(T_amb) = r_a + r_b * T_amb from pump-ON intervals

`project()` integrates the pool temperature forward over the forecast to derive
the predicted "ready" time and required heating hours. The "~3 days to 28 C"
falls out of this — it is never hard-coded.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import const as c
from .forecast import NormalizedForecast
from .options import EngineOptions
from .util import is_active_hour

UTC = timezone.utc

Sample = tuple[datetime, float]          # (time, pool temperature)
Transition = tuple[datetime, bool]       # (time, switch is on)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------
@dataclass
class ThermoModel:
    k: float                 # loss coefficient, 1/h
    r_a: float               # heat-rate intercept, degC/h
    r_b: float               # heat-rate slope per degC ambient
    solar: float             # solar gain at full sun, degC/h
    n_off: int               # usable OFF learning pairs
    n_on: int                # usable ON learning pairs
    r2_k: float              # goodness of the k fit
    confidence: float        # 0..1
    learning: bool           # True while estimates are uncalibrated

    def heat_rate_at(self, amb: float) -> float:
        return _clamp(self.r_a + self.r_b * amb, c.R_MIN, c.R_MAX)

    def loss_rate_at(self, pool: float, amb: float) -> float:
        """degC/h lost to ambient (>=0 when pool warmer than air)."""
        return self.k * max(0.0, pool - amb)

    @classmethod
    def default(cls, options: EngineOptions | None = None) -> "ThermoModel":
        r_a = c.R_PRIOR
        if options and options.pool_volume_l:
            r_a = _prior_heat_rate(options)
        return cls(
            k=c.K_PRIOR, r_a=r_a, r_b=0.0, solar=c.SOLAR_PRIOR,
            n_off=0, n_on=0, r2_k=0.0, confidence=0.0, learning=True,
        )


@dataclass
class Projection:
    predicted_ready: datetime | None
    required_hours: float
    energy_kwh: float | None
    trajectory: list[Sample] = field(default_factory=list)


def _prior_heat_rate(options: EngineOptions) -> float:
    thermal = options.heat_pump_thermal_kw
    if not thermal:
        cop = options.effective_cop()
        thermal = (options.heat_pump_kw or 0.0) * (cop or 0.0)
    denom = (options.pool_volume_l or 0.0) * c.WATER_WH_PER_L_PER_C
    if not thermal or denom <= 0:
        return c.R_PRIOR
    return _clamp(thermal * 1000.0 / denom, c.R_MIN, c.R_MAX)


# ---------------------------------------------------------------------------
# Fitting
# ---------------------------------------------------------------------------
def fit_thermo(
    pool_series: list[Sample],
    switch_transitions: list[Transition],
    ambient_series: list[Sample] | None,
    options: EngineOptions | None = None,
    now: datetime | None = None,
) -> ThermoModel:
    """Fit loss + heat-rate from history; blend with priors when data is thin."""
    pts = _clean_series(pool_series)
    if len(pts) < 3 or not ambient_series:
        return ThermoModel.default(options)

    off_loss: list[float] = []
    off_rate: list[float] = []
    off_w: list[float] = []
    on_items: list[tuple[float, float, float, float]] = []  # amb, rate, loss, weight
    span_off = span_on = 0.0

    for (t0, temp0), (t1, temp1) in zip(pts, pts[1:]):
        dt_h = (t1 - t0).total_seconds() / 3600.0
        if dt_h < c.DT_MIN_H or dt_h > c.DT_MAX_H:
            continue
        on0 = _switch_on_at(switch_transitions, t0)
        on1 = _switch_on_at(switch_transitions, t1)
        if on0 != on1 or _transition_between(switch_transitions, t0, t1):
            continue  # state not homogeneous across the pair
        amb = _ambient_mean(ambient_series, t0, t1)
        if amb is None:
            continue
        rate = (temp1 - temp0) / dt_h
        if abs(rate) > c.SPIKE_MAX_C_PER_H:
            continue  # sensor spike / impossible jump
        t_bar = (temp0 + temp1) / 2.0
        loss = amb - t_bar  # negative when pool warmer than air
        if on0:
            span_on += dt_h
            on_items.append((amb, rate, loss, dt_h))
        else:
            if (t_bar - amb) < c.DT_MIN_GRADIENT_C:
                continue  # too little signal to learn cooling
            off_loss.append(loss)
            off_rate.append(rate)
            off_w.append(dt_h)
            span_off += dt_h

    # k from OFF pairs: rate = k * loss (through origin).
    k_fit, r2 = _wls_origin(off_loss, off_rate, off_w)
    k = _clamp(k_fit, c.K_MIN, c.K_MAX) if k_fit is not None else c.K_PRIOR

    # r_net per ON pair, then linear fit vs ambient.
    amb_xs: list[float] = []
    r_ys: list[float] = []
    r_ws: list[float] = []
    for amb, rate, loss, w in on_items:
        r_net = rate - k * loss
        if r_net < -0.2:
            continue  # pump on yet strongly cooling => misattribution
        amb_xs.append(amb)
        r_ys.append(r_net)
        r_ws.append(w)

    r_a, r_b = _fit_heat_rate(amb_xs, r_ys, r_ws, options)

    n_off, n_on = len(off_w), len(r_ws)
    trusted = (
        n_off >= c.N_OFF_TARGET and span_off >= c.SPAN_OFF_MIN_H
        and (r2 or 0.0) >= c.R2_K_MIN
        and n_on >= c.N_ON_TARGET and span_on >= c.SPAN_ON_MIN_H
    )
    conf = 0.5 * min(1.0, n_off / c.N_OFF_TARGET) + 0.5 * min(1.0, n_on / c.N_ON_TARGET)

    if not trusted:
        # Blend learned values toward priors by confidence.
        prior = ThermoModel.default(options)
        k = conf * k + (1 - conf) * prior.k
        r_a = conf * r_a + (1 - conf) * prior.r_a
        r_b = conf * r_b

    return ThermoModel(
        k=round(k, 5), r_a=round(r_a, 4), r_b=round(r_b, 4), solar=c.SOLAR_PRIOR,
        n_off=n_off, n_on=n_on, r2_k=round(r2 or 0.0, 3),
        confidence=round(conf, 3), learning=not trusted,
    )


def _fit_heat_rate(xs, ys, ws, options) -> tuple[float, float]:
    if len(xs) >= 5:
        a, b = _wls_linear(xs, ys, ws)
        if a is not None:
            return a, b
    if ys:
        total = sum(ws) or len(ys)
        mean = sum(y * w for y, w in zip(ys, ws)) / total
        return _clamp(mean, c.R_MIN, c.R_MAX), 0.0
    return ThermoModel.default(options).r_a, 0.0


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------
def project(
    pool_now: float | None,
    model: ThermoModel,
    forecast: NormalizedForecast,
    options: EngineOptions,
    now: datetime | None = None,
) -> Projection:
    """Integrate forward hour-by-hour to estimate when the pool reaches target."""
    now = (now or datetime.now(UTC)).astimezone(UTC)
    if pool_now is None:
        return Projection(None, 0.0, None, [])

    target = options.target_temp
    temp = pool_now
    ready: datetime | None = None
    heat_hours = 0.0
    traj: list[Sample] = []
    start = _ceil_hour(now)

    for i in range(options.horizon_days * 24):
        cur = start + timedelta(hours=i)
        amb = forecast.temp_at(cur)
        if amb is None:
            amb = temp
        # losses (exact exponential over 1 h)
        temp = amb + (temp - amb) * math.exp(-model.k)
        # solar gain during daytime
        if is_active_hour(cur, options.active_start, options.active_end):
            cloud = forecast.cloud_at(cur)
            solar_frac = max(0.0, 1.0 - cloud / 100.0) if cloud is not None else 0.0
            temp += model.solar * solar_frac
        # heating, if this hour is allowed and we still need it
        if temp < target and _heat_allowed(cur, amb, forecast, options):
            temp += model.heat_rate_at(amb)
            heat_hours += 1.0
        temp = max(temp, amb - 2.0)
        traj.append((cur, round(temp, 2)))
        if ready is None and temp >= target:
            ready = cur
            break

    # projected electrical consumption to reach target = run-hours x input power
    energy = round(heat_hours * options.heat_pump_kw, 2) if options.heat_pump_kw else None
    return Projection(ready, heat_hours, energy, traj)


def _heat_allowed(
    cur: datetime, amb: float, forecast: NormalizedForecast, options: EngineOptions
) -> bool:
    """Optimistic projection policy: heat in suitable daytime hours."""
    if not is_active_hour(cur, options.active_start, options.active_end):
        return False
    if amb < options.min_operating_outdoor_temp:
        return False
    if forecast.rain_within(cur, options.rain_lookahead_h, options.rain_mm_threshold):
        return False
    return True


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------
def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _ceil_hour(dt: datetime) -> datetime:
    dt = dt.astimezone(UTC)
    if dt.minute == 0 and dt.second == 0 and dt.microsecond == 0:
        return dt
    return dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)


def _clean_series(series: list[Sample]) -> list[Sample]:
    """Drop non-numeric points, sort, and median-filter (window 3) for spikes."""
    pts = sorted(
        ((t.astimezone(UTC), float(v)) for t, v in series if _is_num(v)),
        key=lambda e: e[0],
    )
    if len(pts) < 3:
        return pts
    out: list[Sample] = [pts[0]]
    for i in range(1, len(pts) - 1):
        trio = sorted(p[1] for p in pts[i - 1 : i + 2])
        out.append((pts[i][0], trio[1]))  # median of 3 kills single-point spikes
    out.append(pts[-1])
    return out


def _is_num(value) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _switch_on_at(transitions: list[Transition], when: datetime) -> bool:
    state = False
    for t, on in transitions:
        if t <= when:
            state = on
        else:
            break
    return state


def _transition_between(transitions: list[Transition], t0: datetime, t1: datetime) -> bool:
    return any(t0 < t < t1 for t, _ in transitions)


def _ambient_mean(series: list[Sample], t0: datetime, t1: datetime) -> float | None:
    a = _interp_dt(series, t0)
    b = _interp_dt(series, t1)
    if a is None or b is None:
        return None
    return (a + b) / 2.0


def _interp_dt(series: list[Sample], when: datetime) -> float | None:
    if not series:
        return None
    ts = when.timestamp()
    pts = [(t.timestamp(), v) for t, v in series]
    if ts <= pts[0][0]:
        return pts[0][1]
    if ts >= pts[-1][0]:
        return pts[-1][1]
    for i in range(len(pts) - 1):
        t0, v0 = pts[i]
        t1, v1 = pts[i + 1]
        if t0 <= ts <= t1:
            if t1 == t0:
                return v0
            return v0 + (ts - t0) / (t1 - t0) * (v1 - v0)
    return pts[-1][1]


def _wls_origin(xs, ys, ws):
    """Weighted least squares through the origin: y = slope * x."""
    if len(xs) < 3:
        return None, 0.0
    sxx = sum(w * x * x for x, w in zip(xs, ws))
    sxy = sum(w * x * y for x, y, w in zip(xs, ys, ws))
    if sxx <= 0:
        return None, 0.0
    slope = sxy / sxx
    sw = sum(ws) or 1.0
    ybar = sum(w * y for y, w in zip(ys, ws)) / sw
    ss_res = sum(w * (y - slope * x) ** 2 for x, y, w in zip(xs, ys, ws))
    ss_tot = sum(w * (y - ybar) ** 2 for y, w in zip(ys, ws))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return slope, r2


def _wls_linear(xs, ys, ws):
    """Weighted least squares: y = a + b*x. Returns (a, b) or (None, 0)."""
    sw = sum(ws)
    if sw <= 0:
        return None, 0.0
    swx = sum(w * x for x, w in zip(xs, ws))
    swy = sum(w * y for y, w in zip(ys, ws))
    swxx = sum(w * x * x for x, w in zip(xs, ws))
    swxy = sum(w * x * y for x, y, w in zip(xs, ys, ws))
    det = sw * swxx - swx * swx
    if abs(det) < 1e-9:
        return swy / sw, 0.0
    a = (swy * swxx - swx * swxy) / det
    b = (sw * swxy - swx * swy) / det
    return a, b
