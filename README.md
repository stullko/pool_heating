# Pool Heating Controller (Home Assistant / HACS)

A custom Home Assistant integration that decides **when to run a swimming-pool
heat pump** to reach a target temperature (default **28 °C**) as efficiently as
possible — using SHMU weather forecasts, the pool's *learned* heat-loss
behaviour, electricity price and pool filtration. It is **deterministic (no
LLM)** and publishes an explainable **status** so you always see *why* it is or
isn't heating.

## Why

A naive "heat when it's not raining right now and electricity is cheap"
automation can't see that *today* is hopeless but *in four days* there's a warm
window, can't tell whether the water is already at target, and can't estimate
the ~3 days it takes to heat up. This integration adds:

- **Multi-day forecast reasoning** (SHMU ALADIN ≤72 h hourly + ECMWF to ~10 days).
- **Learned thermodynamics** — heat-loss coefficient *k* and heat-up rate are
  fitted from your pool sensor's recorded history (Newton's law of cooling), so
  the "~3 days to 28 °C" estimate is self-calibrating.
- **Cost awareness** — prefer cheap electricity, but catch up in pricier hours
  when a good weather window would otherwise be missed.
- **Hard guardrails** — off at night, only with filtration running, only above a
  minimum outdoor temperature, never when rain is imminent or during a
  long-term cold spell.

## Install (HACS)

1. HACS → *Integrations* → ⋮ → *Custom repositories* → add this repo, category
   **Integration**.
2. Install **Pool Heating Controller**, restart Home Assistant.
3. *Settings → Devices & Services → Add Integration → Pool Heating Controller*.

## Configure

Required: **pool water temperature sensor** and the **heat-pump switch**.
Optional but recommended: outdoor temperature sensor, filtration
(`input_boolean`/`switch`), an "expensive electricity" `binary_sensor`, a
"daytime" `binary_sensor`, a `weather` entity, a **real-time rain-intensity
sensor** (hard "it's raining now" guard), and an **illuminance sensor** (live
solar proxy). SHMU station defaults to `31479` — change it to your nearest
station. **Nothing is hard-coded**, so it works for any pool/location.

All thresholds are tunable later via the integration's **Configure** (options)
dialog: target, hysteresis, night/active window, min operating outdoor temp,
rain and cold thresholds, price policy, compressor min on/off, rain-intensity
threshold, and the heat-pump power. Power defaults to **0.8 kW electrical /
5 kW thermal** (COP ≈ 6.25) — adjust to your unit. COP is derived from
thermal ÷ electrical unless you set it explicitly.

## Entities

| Entity | Purpose |
|---|---|
| `sensor.*_status` | Decision state + `reason` attribute (Slovak), predicted-ready, model confidence |
| `binary_sensor.*_should_heat` | Heating recommendation |
| `select.*_mode` | `auto` / `off` / `force_on` override |
| `sensor.*_predicted_ready` | Estimated time the pool reaches target |
| `sensor.*_required_heating_hours`, `*_energy_needed` | Projections (energy = ON-hours × electrical kW) |
| `sensor.*_power` | Live heat-pump power draw (W) |
| `sensor.*_energy_consumed` | Cumulative consumed energy (kWh, Energy-dashboard ready) |
| `sensor.*_heat_rate`, `*_loss_coefficient`, `*_model_confidence` | Learned model diagnostics |

## Lovelace card

A ready-to-paste **Mushroom-style** dashboard card is in
[`lovelace-card.yaml`](lovelace-card.yaml). It needs the HACS frontend cards
*Mushroom*, *mini-graph-card* and *stack-in-card*. Add it via *Dashboard → Edit
→ Add card → Manual*. It uses `sensor.teplomer_bazen_temperature`,
`switch.sonoff_10013cc5bd` and `sensor.night_state` — change them if your
entities differ. Shows status + colour-coded icon, reason, chips (predicted
ready / power / consumed energy / should-heat), temperatures, battery, the mode
select, and a 72 h graph with night shading. It shows the status + reason, predicted-ready,
mode switch, temperatures, power and consumed energy, plus a 72 h history graph.

## Replacing the old automation

This integration replaces a reactive `switch`-toggling automation. After it is
running and you're happy with the `status` sensor, **disable your old
automation** so the two don't fight over the switch.

## How the decision works

Ordered guardrails → optimisation: mode override → pool-sensor sanity → manual
override → filtration → frost → night/active window → target (+hysteresis) →
forecast availability → outdoor-too-cold-now → rain imminent → long-term cold →
productivity/window → electricity price (cheap-preferred + catch-up) → heat.

## Disclaimer

Not affiliated with SHMÚ. Uses the public SHMU NWP JSON endpoints. Use at your
own risk; the controller fails safe (does not heat) on missing data.
