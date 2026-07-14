"""Tests for the pure deterministic decision engine."""

import math
from datetime import datetime, timezone

from custom_components.pool_heating import const as C
from custom_components.pool_heating import forecast as F
from custom_components.pool_heating import model as M
from custom_components.pool_heating.decision import DecisionInputs, decide
from custom_components.pool_heating.options import build_options

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
OPTS = build_options({})
MODEL = M.ThermoModel.default(OPTS)


def _forecast(warm=True, rain=0.0):
    base = int(NOW.timestamp()) - 12 * 3600

    def ser(step, vals):
        return {"data": [[base + i * step * 3600, v] for i, v in enumerate(vals)]}

    def temp(ts):
        h = ((ts // 3600) + 2) % 24
        amp = 10 if warm else 1
        return round(17 + amp * max(0.0, math.sin(math.pi * (h - 6) / 12)), 1)

    rain_arr = [0.0] * 72
    for i in range(1, 5):
        rain_arr[12 + i] = rain
    aladin = {
        "Air_temperature_at_2m": ser(1, [temp(base + i * 3600) for i in range(72)]),
        "Total_precipitation": ser(1, rain_arr),
        "Total_cloud_cover": ser(1, [30] * 72),
    }
    ecmwf = {
        "Air_temperature_at_2m": ser(3, [temp(base + i * 3 * 3600) for i in range(80)]),
        "Total_precipitation": ser(6, [0.0] * 40),
        "Maximum_temperature_in_the_last_6_hours": ser(6, [(28 if warm else 18)] * 40),
    }
    return F.build_normalized(aladin, ecmwf, NOW)


WARM = _forecast(warm=True)
COLD = _forecast(warm=False)
RAINY = _forecast(warm=True, rain=4.0)


def _decide(**kw):
    kw.setdefault("now", NOW)
    kw.setdefault("outdoor_temp", 22.0)
    kw.setdefault("forecast", WARM)
    kw.setdefault("model", MODEL)
    kw.setdefault("options", OPTS)
    return decide(DecisionInputs(**kw))


def test_heats_when_warm_and_cheap():
    d = _decide(pool_temp=24.0, electricity_expensive=False)
    assert d.should_heat is True
    assert d.status == C.STATUS_HEATING
    assert d.action == C.ACTION_TURN_ON


def test_catches_up_when_expensive_big_deficit():
    d = _decide(pool_temp=24.0, electricity_expensive=True)
    assert d.should_heat is True


def test_waits_for_price_when_expensive_small_deficit():
    d = _decide(pool_temp=27.0, electricity_expensive=True)
    assert d.status == C.STATUS_WAITING_PRICE
    assert d.should_heat is False


def test_cheap_only_never_heats_when_expensive():
    opts = build_options({C.CONF_PRICE_POLICY: C.PRICE_POLICY_CHEAP_ONLY})
    d = decide(
        DecisionInputs(
            now=NOW, pool_temp=24.0, outdoor_temp=22.0, forecast=WARM,
            model=MODEL, options=opts, electricity_expensive=True,
        )
    )
    assert d.status == C.STATUS_WAITING_PRICE


def test_target_reached():
    assert _decide(pool_temp=28.5).status == C.STATUS_TARGET_REACHED


def test_night_off():
    d = _decide(pool_temp=24.0, now=datetime(2026, 6, 1, 23, tzinfo=timezone.utc))
    assert d.status == C.STATUS_NIGHT_OFF
    assert d.action == C.ACTION_TURN_OFF


def test_filtration_required():
    assert _decide(pool_temp=24.0, filtration_on=False).status == C.STATUS_WAITING_FILTRATION


def test_filtration_unavailable_fails_safe():
    d = _decide(pool_temp=24.0, filtration_on=None, filtration_configured=True)
    assert d.status == C.STATUS_WAITING_FILTRATION
    assert d.should_heat is False


def test_frost_protect_survives_unavailable_filtration():
    opts = build_options({C.CONF_FROST_PROTECT: True})
    d = _decide(pool_temp=2.0, options=opts,
                filtration_on=None, filtration_configured=True)
    assert d.status == C.STATUS_FROST_PROTECT
    assert d.should_heat is True


def test_frost_protect_blocked_by_explicitly_off_filtration():
    opts = build_options({C.CONF_FROST_PROTECT: True})
    d = _decide(pool_temp=2.0, options=opts,
                filtration_on=False, filtration_configured=True)
    assert d.status == C.STATUS_WAITING_FILTRATION


def test_outdoor_too_cold_now():
    assert _decide(pool_temp=24.0, outdoor_temp=12.0).status == C.STATUS_WAITING_COLD_NOW


def test_rain_imminent():
    assert _decide(pool_temp=24.0, forecast=RAINY).status == C.STATUS_WAITING_RAIN


def test_live_rain_sensor_blocks():
    d = _decide(pool_temp=24.0, rain_intensity=0.5)
    assert d.status == C.STATUS_WAITING_RAIN
    assert d.should_heat is False


def test_no_live_rain_still_heats():
    d = _decide(pool_temp=24.0, rain_intensity=0.0, electricity_expensive=False)
    assert d.should_heat is True


def test_long_term_cold():
    d = _decide(pool_temp=24.0, outdoor_temp=18.0, forecast=COLD)
    assert d.status == C.STATUS_WAITING_COLD


def test_sensor_unavailable_failsafe():
    d = _decide(pool_temp=None)
    assert d.status == C.STATUS_SENSOR_UNAVAILABLE
    assert d.should_heat is False
    assert d.action == C.ACTION_TURN_OFF


def test_mode_off_and_force_on():
    assert _decide(pool_temp=24.0, mode=C.MODE_OFF).status == C.STATUS_MODE_OFF
    assert _decide(pool_temp=24.0, mode=C.MODE_FORCE_ON).should_heat is True


def test_manual_override_holds():
    d = _decide(pool_temp=24.0, manual_override=True, switch_is_on=True)
    assert d.status == C.STATUS_MANUAL_OVERRIDE
    assert d.action == C.ACTION_HOLD


def test_reason_is_slovak_nonempty():
    d = _decide(pool_temp=24.0)
    assert d.reason_sk and "Hrejem" in d.reason_sk


def test_price_shown_in_waiting_reason():
    d = _decide(pool_temp=27.0, electricity_expensive=True, electricity_price=0.32)
    assert d.status == C.STATUS_WAITING_PRICE
    assert "0.32" in d.reason_sk


def test_energy_cost_estimated_from_price():
    d = _decide(pool_temp=24.0, electricity_expensive=False, electricity_price=0.20)
    assert d.energy_kwh is not None
    assert d.energy_cost_eur == round(d.energy_kwh * 0.20, 2)


def test_trajectory_attached_for_graphing():
    d = _decide(pool_temp=24.0, electricity_expensive=False)
    assert d.trajectory
    when, temp = d.trajectory[0]
    assert when.tzinfo is not None
    assert isinstance(temp, float)
