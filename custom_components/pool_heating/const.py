"""Constants for the Pool Heating Controller integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "pool_heating"
PLATFORMS = ["sensor", "binary_sensor", "select"]

# --- Config (setup) keys ----------------------------------------------------
CONF_NAME = "name"
CONF_POOL_TEMP_ENTITY = "pool_temp_entity"
CONF_HEAT_PUMP_SWITCH = "heat_pump_switch"
CONF_OUTDOOR_TEMP_ENTITY = "outdoor_temp_entity"
CONF_FILTRATION_ENTITY = "filtration_entity"
CONF_ELECTRICITY_EXPENSIVE_ENTITY = "electricity_expensive_entity"
CONF_DAY_ENTITY = "day_entity"
CONF_WEATHER_ENTITY = "weather_entity"
CONF_RAIN_INTENSITY_ENTITY = "rain_intensity_entity"
CONF_ILLUMINANCE_ENTITY = "illuminance_entity"
CONF_PRICE_ENTITY = "price_entity"
CONF_POWER_ENTITY = "power_entity"
CONF_SHMU_STATION = "shmu_station"

# --- Options (tunable) keys -------------------------------------------------
CONF_TARGET_TEMP = "target_temp"
CONF_HYSTERESIS = "hysteresis"
CONF_NIGHT_START = "night_start"
CONF_NIGHT_END = "night_end"
CONF_ACTIVE_START = "active_start"
CONF_ACTIVE_END = "active_end"
CONF_MIN_OPERATING_OUTDOOR_TEMP = "min_operating_outdoor_temp"
CONF_LONGTERM_MAX_THRESHOLD = "longterm_max_threshold"
CONF_COLD_LOOKAHEAD_DAYS = "cold_lookahead_days"
CONF_RAIN_MM_THRESHOLD = "rain_mm_threshold"
CONF_RAIN_LOOKAHEAD_H = "rain_lookahead_h"
CONF_PRICE_POLICY = "price_policy"
CONF_PRICE_EXPENSIVE_THRESHOLD = "price_expensive_threshold"
CONF_CATCHUP_DEFICIT_C = "catchup_deficit_c"
CONF_MIN_ON_MINUTES = "min_on_minutes"
CONF_MIN_OFF_MINUTES = "min_off_minutes"
CONF_MANAGE_FILTRATION = "manage_filtration"
CONF_FROST_PROTECT = "frost_protect_enabled"
CONF_FROST_TEMP = "frost_temp"
CONF_HORIZON_DAYS = "horizon_days"
CONF_RAIN_INTENSITY_THRESHOLD = "rain_intensity_threshold"
CONF_POOL_VOLUME_L = "pool_volume_l"
CONF_HEAT_PUMP_KW = "heat_pump_kw"
CONF_HEAT_PUMP_THERMAL_KW = "heat_pump_thermal_kw"
CONF_COP = "cop"

# --- Defaults ---------------------------------------------------------------
DEFAULT_NAME = "Pool heating"
DEFAULT_SHMU_STATION = 31479
DEFAULT_TARGET_TEMP = 28.0
DEFAULT_HYSTERESIS = 0.5
DEFAULT_NIGHT_START = "21:00:00"
DEFAULT_NIGHT_END = "08:00:00"
DEFAULT_ACTIVE_START = "07:00:00"
DEFAULT_ACTIVE_END = "20:30:00"
DEFAULT_MIN_OPERATING_OUTDOOR_TEMP = 16.0
DEFAULT_LONGTERM_MAX_THRESHOLD = 25.0
DEFAULT_COLD_LOOKAHEAD_DAYS = 4
DEFAULT_RAIN_MM_THRESHOLD = 3.0
DEFAULT_RAIN_LOOKAHEAD_H = 6
DEFAULT_CATCHUP_DEFICIT_C = 2.0
DEFAULT_MIN_ON_MINUTES = 20
DEFAULT_MIN_OFF_MINUTES = 10
DEFAULT_MANAGE_FILTRATION = False
DEFAULT_FROST_PROTECT = False
DEFAULT_FROST_TEMP = 3.0
DEFAULT_HORIZON_DAYS = 10
DEFAULT_RAIN_INTENSITY_THRESHOLD = 0.0
DEFAULT_HEAT_PUMP_KW = 0.8          # electrical input power (kW)
DEFAULT_HEAT_PUMP_THERMAL_KW = 5.0  # thermal output power (kW) -> COP ~6.25
DEFAULT_PRICE_EXPENSIVE_THRESHOLD = 0.30  # EUR/kWh: above this counts as expensive
FULL_SUN_LUX = 100000.0             # illuminance treated as full sun (solar proxy)

# --- Price policy -----------------------------------------------------------
PRICE_POLICY_CHEAP_ONLY = "cheap_only"
PRICE_POLICY_CHEAP_PREFERRED = "cheap_preferred"
PRICE_POLICY_IGNORE = "ignore"
PRICE_POLICIES = [
    PRICE_POLICY_CHEAP_ONLY,
    PRICE_POLICY_CHEAP_PREFERRED,
    PRICE_POLICY_IGNORE,
]
DEFAULT_PRICE_POLICY = PRICE_POLICY_CHEAP_PREFERRED

# --- Operating mode (select entity) -----------------------------------------
MODE_AUTO = "auto"
MODE_OFF = "off"
MODE_FORCE_ON = "force_on"
MODES = [MODE_AUTO, MODE_OFF, MODE_FORCE_ON]
DEFAULT_MODE = MODE_AUTO

# --- Coordinator cadences ---------------------------------------------------
DECISION_INTERVAL = timedelta(minutes=5)
FORECAST_REFRESH = timedelta(minutes=60)
FORECAST_STALE = timedelta(hours=6)   # fail safe: stop trusting a forecast this old
MODEL_REFIT = timedelta(hours=6)
HISTORY_LOOKBACK_DAYS = 14
SENSOR_MAX_AGE = timedelta(minutes=30)

# --- Thermal model priors / bounds ------------------------------------------
K_MIN = 0.002          # 1/h  (slowest cooling, tau ~ 500 h)
K_MAX = 0.05           # 1/h  (fastest cooling, tau ~ 20 h)
R_MIN = 0.05           # degC/h  net heating floor
R_MAX = 1.0            # degC/h  net heating cap
K_PRIOR = 0.0083       # 1/h  ~ 120 h time constant
R_PRIOR = 0.30         # degC/h
SOLAR_PRIOR = 0.05     # degC/h at full sun
SOLAR_MAX = 0.30       # degC/h cap for the learned solar gain
MODEL_ADOPT_RATIO = 0.75  # adopt a fresh fit unless it is this much less confident
N_OFF_TARGET = 30
N_ON_TARGET = 20
SPAN_OFF_MIN_H = 48.0
SPAN_ON_MIN_H = 12.0
R2_K_MIN = 0.5
SPIKE_MAX_C_PER_H = 3.0
DT_MIN_H = 0.25
DT_MAX_H = 6.0
DT_MIN_GRADIENT_C = 1.5
WATER_WH_PER_L_PER_C = 1.163   # Wh to raise 1 L of water by 1 degC

# --- Decision / window tuning ----------------------------------------------
G_MIN_C_PER_H = 0.05           # min net daytime gain to call an hour "productive"

# --- Status codes (state of sensor.<name>_status) ---------------------------
STATUS_HEATING = "heating"
STATUS_TARGET_REACHED = "target_reached"
STATUS_IDLE_BAND = "idle_band"
STATUS_NIGHT_OFF = "night_off"
STATUS_WAITING_FILTRATION = "waiting_filtration"
STATUS_WAITING_COLD_NOW = "waiting_cold_now"
STATUS_WAITING_RAIN = "waiting_rain"
STATUS_WAITING_COLD = "waiting_cold"
STATUS_WAITING_BETTER_WINDOW = "waiting_better_window"
STATUS_WAITING_PRICE = "waiting_price"
STATUS_NO_WINDOW = "no_window"
STATUS_FROST_PROTECT = "frost_protect"
STATUS_MANUAL_OVERRIDE = "manual_override"
STATUS_SENSOR_UNAVAILABLE = "sensor_unavailable"
STATUS_FORECAST_UNAVAILABLE = "forecast_unavailable"
STATUS_COMPRESSOR_PROTECT = "compressor_protect"
STATUS_MODE_OFF = "mode_off"

ALL_STATUSES = [
    STATUS_HEATING,
    STATUS_TARGET_REACHED,
    STATUS_IDLE_BAND,
    STATUS_NIGHT_OFF,
    STATUS_WAITING_FILTRATION,
    STATUS_WAITING_COLD_NOW,
    STATUS_WAITING_RAIN,
    STATUS_WAITING_COLD,
    STATUS_WAITING_BETTER_WINDOW,
    STATUS_WAITING_PRICE,
    STATUS_NO_WINDOW,
    STATUS_FROST_PROTECT,
    STATUS_MANUAL_OVERRIDE,
    STATUS_SENSOR_UNAVAILABLE,
    STATUS_FORECAST_UNAVAILABLE,
    STATUS_COMPRESSOR_PROTECT,
    STATUS_MODE_OFF,
]

# --- Decision actions -------------------------------------------------------
ACTION_TURN_ON = "turn_on"
ACTION_TURN_OFF = "turn_off"
ACTION_HOLD = "hold"      # leave the switch exactly as it is (don't fight it)

# --- SHMU endpoints ---------------------------------------------------------
SHMU_PRODUCTS_URL = "https://www.shmu.sk/api/v1/nwp/getstationproducts?station={station}"
SHMU_DATA_URL = "https://www.shmu.sk/data/datanwp/json/{file_link}"
SHMU_ALADIN_MAX_HOURS = 72   # use ALADIN within this horizon, ECMWF beyond

TIMEZONE = "Europe/Bratislava"
