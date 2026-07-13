"""Tests for the pure thermodynamic model."""

import math
from datetime import datetime, timedelta, timezone

from custom_components.pool_heating import const as C
from custom_components.pool_heating import model as M
from custom_components.pool_heating.options import build_options

START = datetime(2026, 5, 1, tzinfo=timezone.utc)
OPTS = build_options({})


def test_thin_history_returns_learning_default():
    m = M.fit_thermo([], [], None, OPTS)
    assert m.learning is True
    assert m.confidence == 0.0
    assert C.K_MIN <= m.k <= C.K_MAX


def test_newton_cooling_recovers_k():
    amb, k, t0 = 15.0, 0.02, 28.0
    pool, ambient = [], []
    for i in range(130):
        t = START + timedelta(hours=i)
        pool.append((t, round(amb + (t0 - amb) * math.exp(-k * i), 3)))
        ambient.append((t, amb))
    m = M.fit_thermo(pool, [(START, False)], ambient, OPTS, START + timedelta(hours=130))
    assert abs(m.k - k) < 0.005
    assert m.n_off > 30


def test_combined_fit_recovers_k_and_rate():
    amb, k, r = 18.0, 0.02, 0.5
    pool, ambient, trans = [], [], [(START, False)]
    temp = 30.0
    for i in range(120):  # cooling, pump OFF
        t = START + timedelta(hours=i)
        pool.append((t, round(temp, 3)))
        ambient.append((t, amb))
        temp = amb + (temp - amb) * math.exp(-k)
    on = START + timedelta(hours=120)
    trans.append((on, True))
    for i in range(120, 240):  # heating, pump ON
        t = START + timedelta(hours=i)
        pool.append((t, round(temp, 3)))
        ambient.append((t, amb))
        temp = amb + (temp - amb) * math.exp(-k) + r
    m = M.fit_thermo(pool, trans, ambient, OPTS, START + timedelta(hours=240))
    assert abs(m.k - k) < 0.006
    assert m.n_on > 30
    assert abs(m.heat_rate_at(amb) - r) < 0.12
    assert m.learning is False


def test_solar_gain_recovered_from_illuminance():
    """Cooling-only history with a daily sun signal recovers k AND solar."""
    amb, k, solar = 15.0, 0.02, 0.10
    pool, ambient, lux = [], [], []
    temp = 30.0
    for i in range(240):
        t = START + timedelta(hours=i)
        frac = 1.0 if 10 <= (i % 24) <= 16 else 0.0
        pool.append((t, round(temp, 3)))
        ambient.append((t, amb))
        lux.append((t, frac * C.FULL_SUN_LUX))
        temp = amb + (temp - amb) * math.exp(-k) + solar * frac
    m = M.fit_thermo(
        pool, [(START, False)], ambient, OPTS,
        START + timedelta(hours=240), illuminance_series=lux,
    )
    assert abs(m.k - k) < 0.006
    assert abs(m.solar - solar) < 0.04
    assert m.solar > C.SOLAR_PRIOR  # learned, not the prior


def test_no_illuminance_keeps_solar_prior():
    amb, k = 15.0, 0.02
    pool, ambient = [], []
    for i in range(130):
        t = START + timedelta(hours=i)
        pool.append((t, round(amb + (28.0 - amb) * math.exp(-k * i), 3)))
        ambient.append((t, amb))
    m = M.fit_thermo(pool, [(START, False)], ambient, OPTS, START + timedelta(hours=130))
    assert m.solar == C.SOLAR_PRIOR


def test_heat_rate_is_clamped():
    m = M.ThermoModel.default(OPTS)
    assert C.R_MIN <= m.heat_rate_at(-50) <= C.R_MAX
    assert C.R_MIN <= m.heat_rate_at(50) <= C.R_MAX


def test_energy_estimate_from_runtime():
    from custom_components.pool_heating import forecast as F

    base = int(START.timestamp())
    fc = F.build_normalized(
        {
            "Air_temperature_at_2m": {"data": [[base + i * 3600, 24.0] for i in range(120)]},
            "Total_precipitation": {"data": [[base + i * 3600, 0.0] for i in range(120)]},
        },
        None,
        START,
    )
    opts = build_options({})  # default electrical power 0.8 kW
    proj = M.project(24.0, M.ThermoModel.default(opts), fc, opts, START)
    # energy = projected ON hours x electrical kW (no pool volume needed)
    assert proj.energy_kwh is not None
    assert proj.required_hours > 0
    assert abs(proj.energy_kwh - proj.required_hours * 0.8) < 0.05


def test_effective_cop_derives_from_thermal_over_electrical():
    opts = build_options({C.CONF_HEAT_PUMP_KW: 0.8, C.CONF_HEAT_PUMP_THERMAL_KW: 5.0})
    assert abs(opts.effective_cop() - 6.25) < 0.01
