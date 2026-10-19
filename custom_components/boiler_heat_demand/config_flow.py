"""Config and options flow."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_HYSTERESIS,
    CONF_MIN_OFF,
    CONF_MIN_ON,
    CONF_MIN_VALVES,
    CONF_RELAY,
    CONF_VALVES,
    DEFAULT_HYSTERESIS,
    DEFAULT_MIN_OFF,
    DEFAULT_MIN_ON,
    DEFAULT_MIN_VALVES,
    DOMAIN,
)


def _minutes(default: int) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(min=0, max=120, step=1, mode="box", unit_of_measurement="min")
    )


def _tuning_schema(d: dict[str, Any]) -> dict:
    return {
        vol.Required(CONF_MIN_VALVES, default=d.get(CONF_MIN_VALVES, DEFAULT_MIN_VALVES)): selector.NumberSelector(
            selector.NumberSelectorConfig(min=1, max=50, step=1, mode="box")
        ),
        vol.Required(CONF_MIN_ON, default=d.get(CONF_MIN_ON, DEFAULT_MIN_ON)): _minutes(DEFAULT_MIN_ON),
        vol.Required(CONF_MIN_OFF, default=d.get(CONF_MIN_OFF, DEFAULT_MIN_OFF)): _minutes(DEFAULT_MIN_OFF),
        vol.Required(CONF_HYSTERESIS, default=d.get(CONF_HYSTERESIS, DEFAULT_HYSTERESIS)): selector.NumberSelector(
            selector.NumberSelectorConfig(min=0, max=3, step=0.1, mode="box", unit_of_measurement="°C")
        ),
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
