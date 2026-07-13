"""Config and options flows for Pool Heating Controller."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TimeSelector,
)

from . import const as c


def _entity(domain) -> EntitySelector:
    return EntitySelector(EntitySelectorConfig(domain=domain))


def _num(lo, hi, step, unit=None) -> NumberSelector:
    config = NumberSelectorConfig(
        min=lo, max=hi, step=step, mode=NumberSelectorMode.BOX,
    )
    # HA's NumberSelector validates unit_of_measurement as `str`; passing None
    # (key present, value None) raises vol.Invalid and breaks the flow form.
    if unit is not None:
        config["unit_of_measurement"] = unit
    return NumberSelector(config)


class PoolHeatingConfigFlow(ConfigFlow, domain=c.DOMAIN):
    """Initial setup: identity + wiring."""

    VERSION = 1

    async def _async_validate_station(self, station: int) -> str | None:
        """Return an error key when the SHMU station is unusable."""
        from .shmu import ShmuClient, ShmuError

        client = ShmuClient(async_get_clientsession(self.hass), station, timeout=15)
        try:
            if not await client.async_station_has_products():
                return "invalid_station"
        except ShmuError:
            return "cannot_connect"
        return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            station = int(user_input[c.CONF_SHMU_STATION])
            user_input[c.CONF_SHMU_STATION] = station
            error = await self._async_validate_station(station)
            if error is None:
                # One entry per controlled heat pump; the SHMU station may be
                # shared by several pools.
                await self.async_set_unique_id(user_input[c.CONF_HEAT_PUMP_SWITCH])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input.get(c.CONF_NAME, c.DEFAULT_NAME), data=user_input
                )
            errors[c.CONF_SHMU_STATION] = error

        schema = vol.Schema(
            {
                vol.Required(c.CONF_NAME, default=c.DEFAULT_NAME): str,
                vol.Required(c.CONF_POOL_TEMP_ENTITY): _entity("sensor"),
                vol.Required(c.CONF_HEAT_PUMP_SWITCH): _entity("switch"),
                vol.Optional(c.CONF_OUTDOOR_TEMP_ENTITY): _entity("sensor"),
                vol.Optional(c.CONF_FILTRATION_ENTITY): _entity(["input_boolean", "switch"]),
                vol.Optional(c.CONF_ELECTRICITY_EXPENSIVE_ENTITY): _entity("binary_sensor"),
                vol.Optional(c.CONF_PRICE_ENTITY): _entity("sensor"),
                vol.Optional(c.CONF_POWER_ENTITY): _entity("sensor"),
                vol.Optional(c.CONF_DAY_ENTITY): _entity("binary_sensor"),
                vol.Optional(c.CONF_WEATHER_ENTITY): _entity("weather"),
                vol.Optional(c.CONF_RAIN_INTENSITY_ENTITY): _entity("sensor"),
                vol.Optional(c.CONF_ILLUMINANCE_ENTITY): _entity("sensor"),
                vol.Required(c.CONF_SHMU_STATION, default=c.DEFAULT_SHMU_STATION): _num(
                    1, 99999, 1
                ),
            }
        )
        if user_input is not None:
            schema = self.add_suggested_values_to_schema(schema, user_input)
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "PoolHeatingOptionsFlow":
        return PoolHeatingOptionsFlow()


class PoolHeatingOptionsFlow(OptionsFlow):
    """Tunable policy knobs. Do NOT assign self.config_entry (HA provides it)."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        o = self.config_entry.options

        def opt_num(key, default, lo, hi, step, unit=None):
            return (
                vol.Optional(key, default=o.get(key, default)),
                _num(lo, hi, step, unit),
            )

        def maybe_num(key, lo, hi, step, unit=None):
            # optional, may be unset (empty box) — uses suggested_value
            return (
                vol.Optional(key, description={"suggested_value": o.get(key)}),
                _num(lo, hi, step, unit),
            )

        fields = dict(
            [
                opt_num(c.CONF_TARGET_TEMP, c.DEFAULT_TARGET_TEMP, 15, 35, 0.5, "°C"),
                opt_num(c.CONF_HYSTERESIS, c.DEFAULT_HYSTERESIS, 0.1, 3, 0.1, "°C"),
                (
                    vol.Optional(c.CONF_NIGHT_START,
                                 default=o.get(c.CONF_NIGHT_START, c.DEFAULT_NIGHT_START)),
                    TimeSelector(),
                ),
                (
                    vol.Optional(c.CONF_NIGHT_END,
                                 default=o.get(c.CONF_NIGHT_END, c.DEFAULT_NIGHT_END)),
                    TimeSelector(),
                ),
                (
                    vol.Optional(c.CONF_ACTIVE_START,
                                 default=o.get(c.CONF_ACTIVE_START, c.DEFAULT_ACTIVE_START)),
                    TimeSelector(),
                ),
                (
                    vol.Optional(c.CONF_ACTIVE_END,
                                 default=o.get(c.CONF_ACTIVE_END, c.DEFAULT_ACTIVE_END)),
                    TimeSelector(),
                ),
                opt_num(c.CONF_MIN_OPERATING_OUTDOOR_TEMP,
                        c.DEFAULT_MIN_OPERATING_OUTDOOR_TEMP, 0, 30, 0.5, "°C"),
                opt_num(c.CONF_LONGTERM_MAX_THRESHOLD,
                        c.DEFAULT_LONGTERM_MAX_THRESHOLD, 15, 35, 0.5, "°C"),
                opt_num(c.CONF_COLD_LOOKAHEAD_DAYS, c.DEFAULT_COLD_LOOKAHEAD_DAYS, 1, 10, 1),
                opt_num(c.CONF_RAIN_MM_THRESHOLD, c.DEFAULT_RAIN_MM_THRESHOLD, 0, 20, 0.5, "mm"),
                opt_num(c.CONF_RAIN_LOOKAHEAD_H, c.DEFAULT_RAIN_LOOKAHEAD_H, 0, 24, 1, "h"),
                (
                    vol.Optional(
                        c.CONF_PRICE_POLICY,
                        default=o.get(c.CONF_PRICE_POLICY, c.DEFAULT_PRICE_POLICY),
                    ),
                    SelectSelector(
                        SelectSelectorConfig(
                            options=c.PRICE_POLICIES,
                            mode=SelectSelectorMode.DROPDOWN,
                            translation_key="price_policy",
                        )
                    ),
                ),
                opt_num(c.CONF_PRICE_EXPENSIVE_THRESHOLD,
                        c.DEFAULT_PRICE_EXPENSIVE_THRESHOLD, 0, 2, 0.01, "EUR/kWh"),
                opt_num(c.CONF_CATCHUP_DEFICIT_C, c.DEFAULT_CATCHUP_DEFICIT_C, 0, 10, 0.5, "°C"),
                opt_num(c.CONF_MIN_ON_MINUTES, c.DEFAULT_MIN_ON_MINUTES, 0, 180, 5, "min"),
                opt_num(c.CONF_MIN_OFF_MINUTES, c.DEFAULT_MIN_OFF_MINUTES, 0, 180, 5, "min"),
                opt_num(c.CONF_HORIZON_DAYS, c.DEFAULT_HORIZON_DAYS, 1, 10, 1),
                (
                    vol.Optional(
                        c.CONF_MANAGE_FILTRATION,
                        default=o.get(c.CONF_MANAGE_FILTRATION, c.DEFAULT_MANAGE_FILTRATION),
                    ),
                    BooleanSelector(),
                ),
                (
                    vol.Optional(
                        c.CONF_FROST_PROTECT,
                        default=o.get(c.CONF_FROST_PROTECT, c.DEFAULT_FROST_PROTECT),
                    ),
                    BooleanSelector(),
                ),
                opt_num(c.CONF_FROST_TEMP, c.DEFAULT_FROST_TEMP, -5, 15, 0.5, "°C"),
                opt_num(c.CONF_RAIN_INTENSITY_THRESHOLD,
                        c.DEFAULT_RAIN_INTENSITY_THRESHOLD, 0, 100, 0.1),
                opt_num(c.CONF_HEAT_PUMP_KW, c.DEFAULT_HEAT_PUMP_KW, 0, 50, 0.1, "kW"),
                opt_num(c.CONF_HEAT_PUMP_THERMAL_KW,
                        c.DEFAULT_HEAT_PUMP_THERMAL_KW, 0, 100, 0.1, "kW"),
                maybe_num(c.CONF_POOL_VOLUME_L, 0, 200000, 100, "L"),
                maybe_num(c.CONF_COP, 1, 10, 0.1),
            ]
        )
        return self.async_show_form(step_id="init", data_schema=vol.Schema(fields))
