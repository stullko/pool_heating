"""Tests for the pure SHMU forecast normalizer."""

import json
import os
from datetime import datetime, timezone

from custom_components.pool_heating import forecast as F

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return json.load(fh)


def _ser(base, step_h, vals):
    return {"data": [[base + i * step_h * 3600, v] for i, v in enumerate(vals)]}


def test_real_fixtures_normalize():
    aladin = _load("aladin.json")
    ecmwf = _load("ecmwf.json")
    first = aladin["Air_temperature_at_2m"]["data"][0][0]
    now = datetime.fromtimestamp(first + 12 * 3600, timezone.utc)
    fc = F.build_normalized(aladin, ecmwf, now)
    assert fc.run_id
    assert fc.run_at == datetime(2026, 6, 1, 6, 0, tzinfo=timezone.utc)
    assert len(fc.hourly) > 100
    assert len(fc.daily) >= 5
    assert any(h.source == "aladin" for h in fc.hourly)
    assert any(h.source == "ecmwf" for h in fc.hourly)
    assert all(d.total_precip_mm >= 0 for d in fc.daily)


def test_aladin_overrides_ecmwf_near_term():
    base = 1_780_000_000
    aladin = {
        "Air_temperature_at_2m": _ser(base, 1, [10.0] * 72),
        "Total_precipitation": _ser(base, 1, [0.0] * 72),
    }
    ecmwf = {
        "Air_temperature_at_2m": _ser(base, 3, [30.0] * 120),
        "Total_precipitation": _ser(base, 6, [0.0] * 40),
    }
    now = datetime.fromtimestamp(base, timezone.utc)
    fc = F.build_normalized(aladin, ecmwf, now)
    assert fc.hourly[1].temp == 10.0
    assert fc.hourly[1].source == "aladin"
    assert fc.hourly[-1].temp == 30.0
    assert fc.hourly[-1].source == "ecmwf"


def test_rain_within():
    base = 1_780_000_000
    aladin = {
        "Air_temperature_at_2m": _ser(base, 1, [20.0] * 72),
        "Total_precipitation": _ser(base, 1, [0.0, 0.0, 5.0] + [0.0] * 69),
    }
    now = datetime.fromtimestamp(base, timezone.utc)
    fc = F.build_normalized(aladin, None, now)
    assert fc.rain_within(now, 6, 1.0) is True
    assert fc.rain_within(now, 1, 1.0) is False


def test_daymax_below_detects_cold_spell():
    base = 1_780_000_000
    ecmwf = {
        "Air_temperature_at_2m": _ser(base, 3, [18.0] * 80),
        "Maximum_temperature_in_the_last_6_hours": _ser(base, 6, [18.0] * 40),
        "Total_precipitation": _ser(base, 6, [0.0] * 40),
    }
    now = datetime.fromtimestamp(base, timezone.utc)
    fc = F.build_normalized(None, ecmwf, now)
    assert fc.daymax_below(now, 25.0, 4) is True
    assert fc.daymax_below(now, 10.0, 4) is False


def test_missing_fields_no_crash():
    fc = F.build_normalized({}, {}, datetime.now(timezone.utc))
    assert fc.hourly == []
    assert fc.daily == []
    assert fc.current_temp is None


def test_ecmwf_ensemble_rows_use_median_percentile():
    base = 1_780_000_000
    rows = [[base + i * 3600, 10.0, 12.0, 15.0, 18.0, 20.0] for i in range(24)]
    ecmwf = {"Air_temperature_at_2m": {"data": rows}}
    now = datetime.fromtimestamp(base, timezone.utc)
    fc = F.build_normalized(None, ecmwf, now)
    assert fc.hourly[0].temp == 15.0  # p50, not the p10 low bound
    assert fc.current_temp == 15.0
