# Pool Heating Controller

A custom [Home Assistant](https://www.home-assistant.io/) integration (HACS-compatible)
that decides **when to run a swimming-pool heat pump** to reach a target
temperature (default **28 °C**) as efficiently as possible. It combines SHMÚ
weather forecasts, your pool's *learned* heat-loss behaviour, electricity price
and filtration state into one explainable decision. It is **deterministic (no
LLM)** and publishes a **status** that always tells you *why* it is or isn't
heating.

## Why not a simple automation?

A naive "heat when it isn't raining and electricity is cheap" automation can't
see that *today* is hopeless but there's a warm window *in four days*, can't tell
whether the water is already at target, and can't estimate the ~3 days it takes
to heat up. This integration adds:

- **Multi-day forecast reasoning** — SHMÚ ALADIN (≤72 h, hourly) plus ECMWF out
  to ~10 days.
- **Learned thermodynamics** — the heat-loss coefficient *k* and heat-up rate are
  fitted from your pool sensor's recorded history (Newton's law of cooling), so
  the "~3 days to 28 °C" estimate is self-calibrating.
- **Cost awareness** — prefer cheap electricity, but catch up in pricier hours
  when a good weather window would otherwise be missed.
- **Hard guardrails** — off at night, only with filtration running, only above a
  minimum outdoor temperature, never when rain is imminent or during a long-term
  cold spell.

## Requirements

- Home Assistant **2025.1.0** or newer, with the **recorder** enabled — the
  thermal model is learned from recorded pool-sensor history.
- A **pool water temperature sensor** and a **heat-pump switch**.
- *(Optional)* extra sensors for smarter decisions — see
  [Configuration](#configuration).

## Installation

### HACS (recommended)

1. In **HACS → Integrations**, open the ⋮ menu → **Custom repositories**.
2. Add `https://github.com/stullko/pool_heating` with category **Integration**.
3. Install **Pool Heating Controller**, then **restart** Home Assistant.
4. Go to **Settings → Devices & Services → Add Integration** and search for
   **Pool Heating Controller**.

### Manual

Copy the `custom_components/pool_heating` folder into your Home Assistant
`config/custom_components/` directory, restart Home Assistant, then add the
integration as in step 4 above.

## Configuration

Setup is done entirely through the UI config flow.

**Required:** the pool water temperature sensor and the heat-pump switch.

**Optional but recommended:** an outdoor temperature sensor, filtration
(`switch`/`input_boolean`), an "expensive electricity" `binary_sensor` **or a
real electricity-price sensor** (EUR/kWh — above the configurable threshold
counts as expensive), a **heat-pump power sensor** (W or kW, e.g. a measuring
smart plug — used for exact consumption tracking instead of the nominal
rating), a "daytime" `binary_sensor`, a `weather` entity (used as the
outdoor-temperature fallback when the dedicated sensor is missing or stale), a
**real-time rain-intensity sensor** (a hard "it's raining now" guard) and an
**illuminance sensor** (a live solar proxy — its recorded history is also used
to *learn* your pool's solar gain). The SHMÚ station is validated during setup
and defaults to `31479` — change it to the station nearest you. **Nothing is
hard-coded** (the night/active windows follow your Home Assistant timezone), so
it works for any pool or location.

Every threshold can be changed later from the integration's **Configure**
(options) dialog: target temperature, hysteresis, night/active window, minimum
operating outdoor temperature, rain and cold thresholds, price policy, the
expensive-price threshold (EUR/kWh), compressor minimum on/off times,
rain-intensity threshold and the heat-pump power. Power defaults to **0.8 kW
electrical / 5 kW thermal** (COP ≈ 6.25) — adjust it to your unit. COP is
derived from thermal ÷ electrical unless you set it explicitly.

The **wiring** — the pool temperature sensor, the heat-pump switch and every
optional entity — can be changed later too, without deleting the entry (the
learned thermal model survives): open **Settings → Devices & services →
Pool Heating Controller**, click the three-dot menu on the entry and choose
**Reconfigure**. This is the fix when the status is stuck on *Sensor
unavailable* because the configured water-temperature sensor no longer exists
or was renamed. Leaving an optional field empty removes that entity from the
configuration.

The learned thermal model (heat-loss, heat-up rate and solar gain) is
**persisted** per entry, so it survives restarts and recorder purges; a fresh
refit only replaces it when the new fit is at least comparably confident.

## Entities

The integration creates the following entities (the `pool_heating` prefix follows
your integration/device name):

| Entity | Purpose |
|---|---|
| `sensor.pool_heating_status` | Decision state, plus a `reason` attribute (Slovak), predicted-ready time, cost estimate, current price and model confidence |
| `binary_sensor.pool_heating_should_heat` | Heating recommendation |
| `select.pool_heating_mode` | `auto` / `off` / `force_on` override |
| `sensor.pool_heating_predicted_ready` | Estimated time the pool reaches target; its `forecast` attribute carries the projected hour-by-hour temperature trajectory for graphing |
| `sensor.pool_heating_required_heating_hours`, `…_energy_needed` | Projections (energy = ON-hours × electrical kW) |
| `sensor.pool_heating_power` | Live heat-pump power draw (measured sensor when configured, else nominal, W) |
| `sensor.pool_heating_energy_consumed` | Cumulative consumed energy (kWh, Energy-dashboard ready; integrates the measured power when available) |
| `sensor.pool_heating_heat_rate`, `…_loss_coefficient`, `…_model_confidence` | Learned model diagnostics |

The status sensor also reports `compressor_protect` whenever the anti-short-
cycle guard is holding the switch against the engine's wish, with the
remaining minutes in the `reason`.

## Dashboard card (built-in, no dependencies)

The integration **bundles its own Lovelace card** and registers it
automatically — no HACS frontend cards needed. Add it via
**Dashboard → Edit → Add card** and search for **Pool Heating Card**, or in
YAML:

```yaml
type: custom:pool-heating-card
entity: sensor.pool_heating_status   # your status sensor
```

It shows the colour-coded status with the Slovak reason, chips (water/target
and outdoor temperature, predicted-ready time, power, consumed energy, cost
estimate, model confidence), tap-to-switch mode buttons (auto / off / force)
and a 24 h history + multi-day prediction graph with the target line. All
sibling entities are derived from the status sensor id; override them with
`predicted_ready_entity`, `mode_entity`, `power_entity`, `energy_entity`, or
set `hide_graph: true` and `name`.

## Optional YAML cards (Mushroom / apexcharts)

A Mushroom-style dashboard card is also provided in
[`lovelace-card.yaml`](lovelace-card.yaml). It requires the HACS frontend cards
**Mushroom**, **mini-graph-card** and **stack-in-card**. Add it via
**Dashboard → Edit → Add card → Manual** and paste the file's contents.

The card shows the status with a colour-coded icon and reason, chips
(predicted-ready / power / consumed energy / should-heat), water and outdoor
temperatures, battery, the mode selector and a 72 h history graph with night
shading.

The example references the source entities `sensor.teplomer_bazen_temperature`
(pool water), `switch.sonoff_10013cc5bd` (heat pump),
`sensor.pracovna_teplota` (outdoor) and `sensor.night_state` — **replace these
with your own entity IDs**.

A second card, [`lovelace-prediction-card.yaml`](lovelace-prediction-card.yaml)
(requires **apexcharts-card**), graphs the recorded water temperature together
with the model's predicted trajectory from the `forecast` attribute of
`sensor.<name>_predicted_ready`.

## Replacing an existing automation

This integration replaces a reactive, `switch`-toggling automation. Once it is
running and you are happy with the `status` sensor, **disable your old
automation** so the two don't fight over the heat-pump switch.

## Testing

Pytest is configured for Home Assistant **2026.5.4**. Use Python **3.14** and a
fresh virtual environment:

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements_test.txt
.venv/bin/python -m pytest
```

On native Windows, Home Assistant's test harness imports a few Unix-only runner
modules before pytest loads `conftest.py`. Use the test stubs path for local
Windows runs:

```powershell
py -3.14 -m venv .venv314
.venv314\Scripts\python.exe -m pip install -r requirements_test.txt
$env:PYTHONPATH = "$PWD\tests\stubs"
.venv314\Scripts\python.exe -m pytest
Remove-Item Env:PYTHONPATH
```

The existing Windows `.venv` may contain an older Home Assistant test harness;
recreate it before running the tests locally.

### Live dry-run

`scripts/live_check.py` answers *"could it heat right now, and is it worth
it?"* against the **live SHMÚ forecast**, using the same decision engine as
the integration — no Home Assistant required (just `aiohttp`):

```bash
.venv/bin/python scripts/live_check.py --pool 24.5 --price 0.25
```

It prints the current guard conditions, the net heating gain (°C/h), the
energy needed per °C, the most efficient hour of the next 48 h and the
engine's decision + reason for the given water temperature. Without `--pool`
it sweeps a few representative water temperatures.

## How the decision works

Ordered guardrails, then optimisation:

> mode override → pool-sensor sanity → manual override → filtration → frost →
> night/active window → target (+ hysteresis) → forecast availability →
> outdoor-too-cold-now → rain imminent → long-term cold → productivity/window →
> electricity price (cheap-preferred + catch-up) → heat.

## Disclaimer

Not affiliated with SHMÚ. Uses the public SHMÚ NWP JSON endpoints. Use at your
own risk; the controller **fails safe** (does not heat) on missing data.

## License

See [LICENSE](LICENSE).
