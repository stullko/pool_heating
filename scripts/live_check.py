#!/usr/bin/env python3
"""Živá kontrola: dá sa teraz hriať a oplatí sa to?

Stiahne aktuálnu predpoveď SHMÚ pre zadanú stanicu, prebehne ten istý
rozhodovací engine ako integrácia (s defaultnými nastaveniami) a vypíše
rozhodnutie, dôvod a rentabilitu ohrevu. Nepotrebuje Home Assistant —
stačí Python 3.11+ a aiohttp (`pip install aiohttp`).

Príklady:
    python scripts/live_check.py                    # prehľad pre 22/24/26/27.6 °C
    python scripts/live_check.py --pool 24.5        # konkrétna teplota vody
    python scripts/live_check.py --price 0.25       # doplní odhady v EUR
    python scripts/live_check.py --volume 30000     # spresní prior ohrevu

Exit kód: 0 = analýza prebehla, 2 = SHMÚ nedostupné.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import aiohttp

from custom_components.pool_heating import const as c
from custom_components.pool_heating.decision import DecisionInputs, decide, dt_sk
from custom_components.pool_heating.forecast import NormalizedForecast
from custom_components.pool_heating.model import ThermoModel
from custom_components.pool_heating.options import EngineOptions, build_options
from custom_components.pool_heating.shmu import ShmuClient, ShmuError
from custom_components.pool_heating.util import is_active_hour, is_night, to_local

UTC = timezone.utc
SWEEP_POOLS = (22.0, 24.0, 26.0, 27.6)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--station", type=int, default=c.DEFAULT_SHMU_STATION,
                   help=f"SHMÚ stanica (default {c.DEFAULT_SHMU_STATION})")
    p.add_argument("--pool", type=float, default=None,
                   help="aktuálna teplota vody v °C (bez zadania sa ukáže prehľad)")
    p.add_argument("--target", type=float, default=None,
                   help=f"cieľová teplota (default {c.DEFAULT_TARGET_TEMP})")
    p.add_argument("--volume", type=float, default=None,
                   help="objem bazéna v litroch (spresní odhad rýchlosti ohrevu)")
    p.add_argument("--price", type=float, default=None,
                   help="cena elektriny v EUR/kWh (doplní odhady nákladov)")
    return p.parse_args()


async def _fetch(station: int) -> NormalizedForecast:
    async with aiohttp.ClientSession() as session:
        return await ShmuClient(session, station).async_get_forecast()


def _gain(model: ThermoModel, opts: EngineOptions, amb: float) -> float:
    """Čistý zisk °C/h pri ohreve: ohrev mínus strata pri cieľovej teplote."""
    return model.heat_rate_at(amb) - model.loss_rate_at(opts.target_temp, amb)


def _best_hour(
    fc: NormalizedForecast, model: ThermoModel, opts: EngineOptions, now: datetime
) -> tuple[datetime, float] | None:
    """Hodina s najvyšším čistým ziskom v najbližších 48 h (v povolenom okne)."""
    best: tuple[datetime, float] | None = None
    horizon = now + timedelta(hours=48)
    for h in fc.hourly:
        if h.time <= now or h.time > horizon or h.temp is None:
            continue
        if not is_active_hour(h.time, opts.active_start, opts.active_end):
            continue
        if h.temp < opts.min_operating_outdoor_temp:
            continue
        if fc.rain_within(h.time, opts.rain_lookahead_h, opts.rain_mm_threshold):
            continue
        gain = _gain(model, opts, h.temp)
        if gain > 0 and (best is None or gain > best[1]):
            best = (h.time, gain)
    return best


def _fmt(value: float | None, suffix: str = "", nd: int = 2) -> str:
    return "—" if value is None else f"{value:.{nd}f}{suffix}"


def _conditions_report(
    fc: NormalizedForecast, opts: EngineOptions, now: datetime, amb: float | None
) -> None:
    def row(ok: bool, label: str, detail: str) -> None:
        print(f"  [{'OK' if ok else 'NIE'}] {label:<28} {detail}")

    night = is_night(now, opts.night_start, opts.night_end)
    active = is_active_hour(now, opts.active_start, opts.active_end)
    rain_mm = fc.precip_sum(now, now + timedelta(hours=opts.rain_lookahead_h))
    rainy = fc.rain_within(now, opts.rain_lookahead_h, opts.rain_mm_threshold)
    cold_spell = fc.daymax_below(now, opts.longterm_max_threshold, opts.cold_lookahead_days)
    warm_enough = amb is not None and amb >= opts.min_operating_outdoor_temp

    print("Podmienky teraz:")
    row(not night and active, "denné okno",
        f"{opts.active_start[:5]}–{opts.active_end[:5]}, teraz {to_local(now).strftime('%H:%M')}")
    row(warm_enough, "vonkajšia teplota",
        f"{_fmt(amb, ' °C', 1)} (minimum {opts.min_operating_outdoor_temp:.0f} °C)")
    row(not rainy, "dážď najbližších h",
        f"~{rain_mm:.1f} mm / {opts.rain_lookahead_h} h (prah {opts.rain_mm_threshold:.0f} mm)")
    row(not cold_spell, "dlhodobý výhľad",
        f"denné maximá nasledujúcich {opts.cold_lookahead_days} dní vs prah "
        f"{opts.longterm_max_threshold:.0f} °C")


def _profitability_report(
    fc: NormalizedForecast,
    model: ThermoModel,
    opts: EngineOptions,
    now: datetime,
    amb: float | None,
    price: float | None,
) -> None:
    print("\nRentabilita:")
    if amb is None:
        print("  Bez aktuálnej vonkajšej teploty sa rentabilita nedá vyčísliť.")
        return

    gain_now = _gain(model, opts, amb)
    kw = opts.heat_pump_kw or 0.0
    if gain_now > 0:
        kwh_per_deg = kw / gain_now
        cost = f" (~{kwh_per_deg * price:.2f} EUR/°C)" if price else ""
        print(f"  Čistý zisk teraz: {gain_now:.2f} °C/h  ->  "
              f"{kwh_per_deg:.1f} kWh na 1 °C{cost}")
    else:
        print(f"  Čistý zisk teraz: {gain_now:.2f} °C/h — strata do vzduchu je väčšia"
              " ako výkon ohrevu.")

    best = _best_hour(fc, model, opts, now)
    if best is not None:
        best_at, best_gain = best
        if gain_now > 0 and best_gain > gain_now * 1.05:
            saving = (1 - gain_now / best_gain) * 100
            print(f"  Najvýhodnejšia hodina do 48 h: {dt_sk(best_at)} "
                  f"({best_gain:.2f} °C/h, o ~{saving:.0f} % menej energie na °C)")
        else:
            print(f"  Teraz je prakticky najvýhodnejší čas do 48 h "
                  f"(maximum {best_gain:.2f} °C/h o {dt_sk(best_at)}).")
    else:
        print("  V najbližších 48 h nie je žiadna vhodná hodina na ohrev.")

    if gain_now >= c.G_MIN_C_PER_H:
        print("  VERDIKT: ohrev je teraz rentabilný.")
    elif gain_now > 0:
        print("  VERDIKT: hraničné — engine by počkal na výhodnejšie okno.")
    else:
        print("  VERDIKT: ohrev sa teraz neoplatí.")


def _decision_report(
    fc: NormalizedForecast,
    model: ThermoModel,
    opts: EngineOptions,
    now: datetime,
    pools: tuple[float, ...],
    price: float | None,
) -> None:
    print("\nRozhodnutie enginu podľa teploty vody:")
    for pool in pools:
        d = decide(DecisionInputs(
            now=now, pool_temp=pool, outdoor_temp=None,
            forecast=fc, model=model, options=opts,
        ))
        verdict = "HREJEM" if d.should_heat else "NEHREJEM"
        cost = ""
        if price and d.energy_kwh:
            cost = f", ~{d.energy_kwh * price:.2f} EUR"
        extras = (f"dohriatie {dt_sk(d.predicted_ready)}, "
                  f"{_fmt(d.required_hours, ' h', 1)} chodu, "
                  f"{_fmt(d.energy_kwh, ' kWh', 1)}{cost}")
        print(f"  voda {pool:>4.1f} °C -> {verdict} [{d.status}] {extras}")
        print(f"       {d.reason_sk}")


def main() -> int:
    args = _parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - len kozmetika konzoly
        pass

    overrides = {
        c.CONF_TARGET_TEMP: args.target,
        c.CONF_POOL_VOLUME_L: args.volume,
    }
    opts = build_options({k: v for k, v in overrides.items() if v is not None})
    model = ThermoModel.default(opts)
    now = datetime.now(UTC)

    print(f"SHMÚ stanica {args.station}, {to_local(now).strftime('%A %d.%m.%Y %H:%M %Z')}"
          f" — cieľ {opts.target_temp:.1f} °C")
    try:
        fc = asyncio.run(_fetch(args.station))
    except ShmuError as err:
        print(f"CHYBA: SHMÚ nedostupné: {err}")
        return 2

    print(f"Predpoveď: beh {fc.run_id}, {len(fc.hourly)} hodín, "
          f"{len(fc.daily)} dní, aktuálne vonku {_fmt(fc.current_temp, ' °C', 1)}")
    days = ", ".join(
        f"{d.day.strftime('%a %d.%m.')} max {_fmt(d.temp_max, '', 1)} °C"
        + (f" dážď {d.total_precip_mm:.0f} mm" if d.total_precip_mm >= 1 else "")
        for d in fc.daily[:6]
    )
    print(f"Denné maximá: {days}\n")

    amb = fc.current_temp
    _conditions_report(fc, opts, now, amb)
    _profitability_report(fc, model, opts, now, amb, args.price)

    pools = (args.pool,) if args.pool is not None else SWEEP_POOLS
    _decision_report(fc, model, opts, now, pools, args.price)

    print("\nPoznámka: bez histórie z Home Assistanta počíta skript s priormi "
          f"(ohrev ~{model.r_a:.2f} °C/h, strata k={model.k}/h); nainštalovaná "
          "integrácia používa naučený model.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
