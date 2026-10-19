"""Config and options flow."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_DEMAND_MODE,
    CONF_HYSTERESIS,
    CONF_MIN_OFF,
    CONF_MIN_ON,
    CONF_MIN_VALVES,
    CONF_NOTIFY,
    CONF_RELAY,
    CONF_RELAY_TIMEOUT,
    CONF_SAFETY_MIN_TEMP,
    CONF_START_DEFICIT,
    CONF_STOP_DEFICIT,
    CONF_VALVE_FAILSAFE,
    CONF_VALVES,
    CONF_VALVE_TIMEOUT,
    DEFAULT_DEMAND_MODE,
    DEFAULT_HYSTERESIS,
    DEFAULT_MIN_OFF,
    DEFAULT_MIN_ON,
    DEFAULT_MIN_VALVES,
    DEFAULT_RELAY_TIMEOUT,
    DEFAULT_SAFETY_MIN_TEMP,
    DEFAULT_START_DEFICIT,
    DEFAULT_STOP_DEFICIT,
    DEFAULT_VALVE_FAILSAFE,
    DEFAULT_VALVE_TIMEOUT,
    DOMAIN,
)
from .demand import FAILSAFE_HEAT, FAILSAFE_HOLD, FAILSAFE_IGNORE, MODE_COUNT, MODE_DEFICIT


def _minutes(default: int) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(min=0, max=120, step=1, mode="box", unit_of_measurement="min")
    )


def _timeout_minutes() -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0, max=1440, step=1, mode="box", unit_of_measurement="min"
        )
    )


def _degrees(max_value: float) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0, max=max_value, step=0.1, mode="box", unit_of_measurement="°C"
        )
    )


_DEMAND_MODES = [
    selector.SelectOptionDict(value=MODE_COUNT, label="Number of valves calling for heat"),
    selector.SelectOptionDict(value=MODE_DEFICIT, label="Temperature deficit (target - current)"),
]
_FAILSAFES = [
    selector.SelectOptionDict(value=FAILSAFE_IGNORE, label="Ignore the valve (no demand)"),
    selector.SelectOptionDict(value=FAILSAFE_HEAT, label="Assume it calls for heat"),
    selector.SelectOptionDict(value=FAILSAFE_HOLD, label="Keep its last known demand"),
]


def _tuning_schema(d: dict[str, Any]) -> dict:
    return {
        vol.Required(CONF_DEMAND_MODE, default=d.get(CONF_DEMAND_MODE, DEFAULT_DEMAND_MODE)): selector.SelectSelector(
            selector.SelectSelectorConfig(options=_DEMAND_MODES, mode="dropdown")
        ),
        vol.Required(CONF_MIN_VALVES, default=d.get(CONF_MIN_VALVES, DEFAULT_MIN_VALVES)): selector.NumberSelector(
            selector.NumberSelectorConfig(min=1, max=50, step=1, mode="box")
        ),
        vol.Required(CONF_START_DEFICIT, default=d.get(CONF_START_DEFICIT, DEFAULT_START_DEFICIT)): _degrees(10),
        vol.Required(CONF_STOP_DEFICIT, default=d.get(CONF_STOP_DEFICIT, DEFAULT_STOP_DEFICIT)): _degrees(10),
        vol.Required(CONF_MIN_ON, default=d.get(CONF_MIN_ON, DEFAULT_MIN_ON)): _minutes(DEFAULT_MIN_ON),
        vol.Required(CONF_MIN_OFF, default=d.get(CONF_MIN_OFF, DEFAULT_MIN_OFF)): _minutes(DEFAULT_MIN_OFF),
        vol.Required(CONF_HYSTERESIS, default=d.get(CONF_HYSTERESIS, DEFAULT_HYSTERESIS)): selector.NumberSelector(
            selector.NumberSelectorConfig(min=0, max=3, step=0.1, mode="box", unit_of_measurement="°C")
        ),
        vol.Required(CONF_SAFETY_MIN_TEMP, default=d.get(CONF_SAFETY_MIN_TEMP, DEFAULT_SAFETY_MIN_TEMP)): _degrees(30),
        vol.Required(
            CONF_VALVE_TIMEOUT,
            default=d.get(CONF_VALVE_TIMEOUT, DEFAULT_VALVE_TIMEOUT),
        ): _timeout_minutes(),
        vol.Required(CONF_VALVE_FAILSAFE, default=d.get(CONF_VALVE_FAILSAFE, DEFAULT_VALVE_FAILSAFE)): selector.SelectSelector(
            selector.SelectSelectorConfig(options=_FAILSAFES, mode="dropdown")
        ),
        vol.Required(CONF_RELAY_TIMEOUT, default=d.get(CONF_RELAY_TIMEOUT, DEFAULT_RELAY_TIMEOUT)): selector.NumberSelector(
            selector.NumberSelectorConfig(min=1, max=120, step=1, mode="box", unit_of_measurement="min")
        ),
        vol.Optional(CONF_NOTIFY, description={"suggested_value": d.get(CONF_NOTIFY)}): selector.TextSelector(),
    }


class BoilerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_RELAY])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title="Boiler", data=user_input)
        schema = {
            vol.Required(CONF_RELAY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["switch", "input_boolean"])
            ),
            vol.Required(CONF_VALVES): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate", multiple=True)
            ),
            **_tuning_schema({}),
        }
        return self.async_show_form(step_id="user", data_schema=vol.Schema(schema))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return BoilerOptionsFlow()


class BoilerOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        cur = {**self.config_entry.data, **self.config_entry.options}
        schema = {
            vol.Required(CONF_RELAY, default=cur[CONF_RELAY]): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["switch", "input_boolean"])
            ),
            vol.Required(CONF_VALVES, default=cur[CONF_VALVES]): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate", multiple=True)
            ),
            **_tuning_schema(cur),
        }
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))
