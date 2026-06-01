"""Pure SHMU forecast normalization (no Home Assistant imports).

Merges SHMU ALADIN (precise, <=72 h, hourly) and ECMWF (coarse, up to ~10 days)
into one uniform hourly series plus per-day aggregates, and exposes the
predicates the decision engine needs (rain soon, long-term cold, next warm
window). Every field is read defensively: ALADIN and ECMWF expose different
keys, so a missing field yields an empty series rather than an error.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from .const import SHMU_ALADIN_MAX_HOURS
from .util import hour_floor_ts, is_active_hour, to_local

UTC = timezone.utc

# Candidate SHMU field names (ALADIN + ECMWF share most; some are ECMWF-only).
_TEMP_KEY = "Air_temperature_at_2m"
_PRECIP_KEY = "Total_precipitation"
_CLOUD_KEY = "Total_cloud_cover"
_WIND_KEY = "Wind_speed_at_10m"
_TMAX6_KEY = "Maximum_temperature_in_the_last_6_hours"
_TMIN6_KEY = "Minimum_temperature_in_the_last_6_hours"

Pair = tuple[int, float | None]


@dataclass
class HourPoint:
    """One hour of normalized forecast (timestamp is UTC, hour-aligned)."""

    time: datetime
    temp: float | None
    precip_mm: float
    cloud_pct: float | None
    wind_ms: float | None
    source: str  # "aladin" | "ecmwf"


@dataclass
class DayAgg:
    """Per-(local-)day aggregate."""

    day: date
    temp_min: float | None
    temp_max: float | None
    total_precip_mm: float
    mean_cloud_pct: float | None


@dataclass
class NormalizedForecast:
    """Merged, timezone-correct forecast consumed by model + decision."""

    run_id: str
    generated_at: datetime | None
    hourly: list[HourPoint]
    daily: list[DayAgg]
    current_temp: float | None
    next_rain_at: datetime | None

    # ---- lookups -----------------------------------------------------------
    def temp_at(self, when: datetime) -> float | None:
        """Linear-interpolated air temperature at an arbitrary instant."""
        return _interp([(int(h.time.timestamp()), h.temp) for h in self.hourly],
                       int(when.timestamp()))

    def cloud_at(self, when: datetime) -> float | None:
        """Linear-interpolated total cloud cover (%) at an arbitrary instant."""
        return _interp([(int(h.time.timestamp()), h.cloud_pct) for h in self.hourly],
                       int(when.timestamp()))

    def precip_sum(self, start: datetime, end: datetime) -> float:
        """Total forecast precipitation (mm) in [start, end)."""
        s, e = int(start.timestamp()), int(end.timestamp())
        return round(sum(h.precip_mm for h in self.hourly
                         if s <= int(h.time.timestamp()) < e), 2)

    def day_agg(self, day: date) -> DayAgg | None:
        for d in self.daily:
            if d.day == day:
                return d
        return None

    # ---- predicates --------------------------------------------------------
    def rain_within(self, now: datetime, hours: int, mm_threshold: float) -> bool:
        """True if forecast precipitation over the next `hours` reaches threshold."""
        return self.precip_sum(now, now + timedelta(hours=hours)) >= mm_threshold

    def daymax_below(self, now: datetime, threshold: float, horizon_days: int) -> bool:
        """True if EVERY day from today over the horizon stays below threshold.

        Models "dlhodobo nebude viac ako 25 stupnov": a persistent cold spell.
        Returns False if we have no daily data to judge.
        """
        today = to_local(now).date()
        end = today + timedelta(days=horizon_days)
        considered = [d for d in self.daily if today <= d.day < end
                      and d.temp_max is not None]
        if not considered:
            return False
        return all(d.temp_max < threshold for d in considered)

    def next_warm_window(
        self,
        now: datetime,
        *,
        min_temp: float,
        daily_max_threshold: float,
        rain_mm: float,
        rain_window_h: int,
        active_start: str,
        active_end: str,
    ) -> datetime | None:
        """First future daytime hour whose conditions are suitable to heat.

        Suitable = inside the active (daytime) window, air temp >= min_temp,
        that local day's max >= threshold, and no imminent rain. Used both as
        the WAIT target and for the "next window" shown in the status.
        """
        for h in self.hourly:
            if h.time <= now or h.temp is None:
                continue
            if not is_active_hour(h.time, active_start, active_end):
                continue
            if h.temp < min_temp:
                continue
            day = self.day_agg(to_local(h.time).date())
            if day is None or day.temp_max is None or day.temp_max < daily_max_threshold:
                continue
            if self.rain_within(h.time, rain_window_h, rain_mm):
                continue
            return h.time
        return None


# ---------------------------------------------------------------------------
# Parsing / building
# ---------------------------------------------------------------------------
def _series(fields: dict | None, key: str) -> list[Pair]:
    """Extract a sorted [(unix_ts, value|None)] series for a SHMU field."""
    if not isinstance(fields, dict):
        return []
    node = fields.get(key)
    if not isinstance(node, dict):
        return []
    data = node.get("data")
    if not isinstance(data, list):
        return []
    out: list[Pair] = []
    for entry in data:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            continue
        ts_raw, val_raw = entry[0], entry[1]
        try:
            ts = int(ts_raw)
        except (TypeError, ValueError):
            continue
        if val_raw is None:
            out.append((ts, None))
            continue
        try:
            out.append((ts, float(val_raw)))
        except (TypeError, ValueError):
            out.append((ts, None))
    out.sort(key=lambda e: e[0])
    return out


def _interp(series: list[Pair], ts: int) -> float | None:
    """Linear interpolation with hold-last/hold-first at the edges."""
    if not series:
        return None
    if ts <= series[0][0]:
        return series[0][1]
    if ts >= series[-1][0]:
        return series[-1][1]
    for i in range(len(series) - 1):
        t0, v0 = series[i]
        t1, v1 = series[i + 1]
        if t0 <= ts <= t1:
            if v0 is None:
                return v1
            if v1 is None:
                return v0
            if t1 == t0:
                return v0
            frac = (ts - t0) / (t1 - t0)
            return v0 + frac * (v1 - v0)
    return series[-1][1]


def _pick(aladin: list[Pair], ecmwf: list[Pair], cutoff_ts: int) -> list[Pair]:
    """Prefer ALADIN within the cutoff horizon, ECMWF beyond it."""
    if aladin:
        merged = [p for p in aladin if p[0] <= cutoff_ts]
        merged += [p for p in ecmwf if p[0] > cutoff_ts]
        if merged:
            merged.sort(key=lambda e: e[0])
            return merged
    return list(ecmwf)


def _distribute_precip(series: list[Pair]) -> dict[int, float]:
    """Spread each precipitation bucket evenly over the hours it covers.

    ALADIN buckets are ~1 h, ECMWF ~6 h. The amount at timestamp `ts` is the
    precipitation accumulated in the bucket ending at `ts`.
    """
    out: dict[int, float] = {}
    prev_ts: int | None = None
    for ts, val in series:
        if val is None or val <= 0:
            prev_ts = ts
            continue
        if prev_ts is None:
            bucket_h = 1
        else:
            bucket_h = max(1, round((ts - prev_ts) / 3600))
        bucket_h = min(bucket_h, 6)
        per_hour = val / bucket_h
        for i in range(bucket_h):
            hour_start = hour_floor_ts(ts) - (i + 1) * 3600
            out[hour_start] = out.get(hour_start, 0.0) + per_hour
        prev_ts = ts
    return out


def _run_id(raw: dict | None) -> str:
    if isinstance(raw, dict):
        for key in ("data_date_time", "model_name"):
            if raw.get(key):
                return str(raw[key])
    return ""


def build_normalized(
    aladin: dict | None,
    ecmwf: dict | None,
    now: datetime | None = None,
) -> NormalizedForecast:
    """Build a NormalizedForecast from raw ALADIN and/or ECMWF field maps."""
    now = (now or datetime.now(UTC)).astimezone(UTC)
    cutoff_ts = int((now + timedelta(hours=SHMU_ALADIN_MAX_HOURS)).timestamp())

    temp = _pick(_series(aladin, _TEMP_KEY), _series(ecmwf, _TEMP_KEY), cutoff_ts)
    precip = _pick(_series(aladin, _PRECIP_KEY), _series(ecmwf, _PRECIP_KEY), cutoff_ts)
    cloud = _pick(_series(aladin, _CLOUD_KEY), _series(ecmwf, _CLOUD_KEY), cutoff_ts)
    wind = _pick(_series(aladin, _WIND_KEY), _series(ecmwf, _WIND_KEY), cutoff_ts)

    precip_by_hour = _distribute_precip(precip)

    if not temp:
        run_id = _run_id(aladin) or _run_id(ecmwf)
        return NormalizedForecast(run_id, None, [], [], None, None)

    start_hour = hour_floor_ts(temp[0][0])
    end_hour = hour_floor_ts(temp[-1][0])
    hourly: list[HourPoint] = []
    h = start_hour
    while h <= end_hour:
        in_aladin = bool(aladin) and h <= cutoff_ts
        hourly.append(
            HourPoint(
                time=datetime.fromtimestamp(h, UTC),
                temp=_round1(_interp(temp, h)),
                precip_mm=round(precip_by_hour.get(h, 0.0), 3),
                cloud_pct=_round1(_interp(cloud, h)),
                wind_ms=_round1(_interp(wind, h)),
                source="aladin" if in_aladin else "ecmwf",
            )
        )
        h += 3600

    daily = _aggregate_days(
        hourly,
        max6=_pick(_series(aladin, _TMAX6_KEY), _series(ecmwf, _TMAX6_KEY), cutoff_ts),
        min6=_pick(_series(aladin, _TMIN6_KEY), _series(ecmwf, _TMIN6_KEY), cutoff_ts),
    )

    current_temp = _round1(_interp(temp, int(now.timestamp())))
    next_rain_at = next(
        (hp.time for hp in hourly if hp.time > now and hp.precip_mm > 0.1), None
    )

    return NormalizedForecast(
        run_id=_run_id(aladin) or _run_id(ecmwf),
        generated_at=now,
        hourly=hourly,
        daily=daily,
        current_temp=current_temp,
        next_rain_at=next_rain_at,
    )


def _aggregate_days(
    hourly: list[HourPoint], max6: list[Pair], min6: list[Pair]
) -> list[DayAgg]:
    buckets: dict[date, dict] = {}
    for hp in hourly:
        d = to_local(hp.time).date()
        b = buckets.setdefault(
            d, {"temps": [], "precip": 0.0, "clouds": []}
        )
        if hp.temp is not None:
            b["temps"].append(hp.temp)
        b["precip"] += hp.precip_mm
        if hp.cloud_pct is not None:
            b["clouds"].append(hp.cloud_pct)

    # Fold in ECMWF explicit 6 h min/max (more accurate than hourly sampling).
    for ts, val in max6:
        if val is None:
            continue
        d = to_local(datetime.fromtimestamp(ts, UTC)).date()
        if d in buckets:
            buckets[d].setdefault("temps", []).append(val)
    for ts, val in min6:
        if val is None:
            continue
        d = to_local(datetime.fromtimestamp(ts, UTC)).date()
        if d in buckets:
            buckets[d].setdefault("temps", []).append(val)

    out: list[DayAgg] = []
    for d in sorted(buckets):
        b = buckets[d]
        temps = b["temps"]
        clouds = b["clouds"]
        out.append(
            DayAgg(
                day=d,
                temp_min=_round1(min(temps)) if temps else None,
                temp_max=_round1(max(temps)) if temps else None,
                total_precip_mm=round(b["precip"], 2),
                mean_cloud_pct=_round1(sum(clouds) / len(clouds)) if clouds else None,
            )
        )
    return out


def _round1(value: float | None) -> float | None:
    return None if value is None else round(value, 1)
