"""Config and options flow."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_ADD_ANOTHER,
    CONF_DEMAND_MODE,
    CONF_EDIT_ROOMS,
    CONF_ROOM_NAME,
    CONF_ROOM_SENSOR,
    CONF_ROOM_VALVES,
    CONF_HYSTERESIS,
    CONF_LEARNING,
    CONF_MIN_OFF,
    CONF_MIN_ON,
    CONF_MIN_VALVES,
    CONF_NOTIFY,
    CONF_OUTDOOR,
    CONF_RELAY,
    CONF_RELAY_TIMEOUT,
    CONF_ROOMS,
    CONF_SAFETY_MIN_TEMP,
    CONF_START_DEFICIT,
    CONF_STOP_DEFICIT,
    CONF_VALVE_FAILSAFE,
    CONF_VALVES,
    CONF_VALVE_TIMEOUT,
    DEFAULT_DEMAND_MODE,
    DEFAULT_HYSTERESIS,
    DEFAULT_LEARNING,
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
        vol.Required(CONF_LEARNING, default=d.get(CONF_LEARNING, DEFAULT_LEARNING)): selector.BooleanSelector(),
        vol.Optional(CONF_OUTDOOR, description={"suggested_value": d.get(CONF_OUTDOOR)}): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=["sensor", "weather"])
        ),
    }


class _RoomsMixin:
    """Collects room groupings: repeat the room step until the user is done."""

    _data: dict[str, Any]
    _rooms: list[dict[str, Any]]

    def _room_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Optional(CONF_ROOM_NAME): selector.TextSelector(),
                vol.Optional(CONF_ROOM_VALVES): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="climate", multiple=True, include_entities=list(self._data[CONF_VALVES])
                    )
                ),
                vol.Optional(CONF_ROOM_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Required(CONF_ADD_ANOTHER, default=False): selector.BooleanSelector(),
            }
        )

    async def async_step_rooms(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            name = (user_input.get(CONF_ROOM_NAME) or "").strip()
            valves = user_input.get(CONF_ROOM_VALVES) or []
            if name or valves:
                taken = {e for r in self._rooms for e in r[CONF_ROOM_VALVES]}
                if not name or not valves:
                    errors["base"] = "room_incomplete"
                elif any(e in taken for e in valves) or name in {r[CONF_ROOM_NAME] for r in self._rooms}:
                    errors["base"] = "room_duplicate"
                else:
                    self._rooms.append(
                        {
                            "name": name,
                            "valves": list(valves),
                            "temp_sensor": user_input.get(CONF_ROOM_SENSOR) or None,
                        }
                    )
            if not errors and not user_input.get(CONF_ADD_ANOTHER):
                return await self._finish()
            if not errors:
                return self.async_show_form(step_id="rooms", data_schema=self._room_schema())
        return self.async_show_form(
            step_id="rooms", data_schema=self._room_schema(), errors=errors
        )

    async def _finish(self):
        raise NotImplementedError


class BoilerConfigFlow(_RoomsMixin, config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_RELAY])
            self._abort_if_unique_id_configured()
            self._data = dict(user_input)
            self._rooms = []
            return await self.async_step_rooms()
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

    async def _finish(self):
        return self.async_create_entry(title="Boiler", data={**self._data, CONF_ROOMS: self._rooms})

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return BoilerOptionsFlow()


class BoilerOptionsFlow(_RoomsMixin, config_entries.OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        cur = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            redefine = user_input.pop(CONF_EDIT_ROOMS, False)
            self._data = dict(user_input)
            if redefine:
                self._rooms = []
                return await self.async_step_rooms()
            self._rooms = cur.get(CONF_ROOMS, [])
            return await self._finish()
        schema = {
            vol.Required(CONF_RELAY, default=cur[CONF_RELAY]): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["switch", "input_boolean"])
            ),
            vol.Required(CONF_VALVES, default=cur[CONF_VALVES]): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate", multiple=True)
            ),
            vol.Required(CONF_EDIT_ROOMS, default=False): selector.BooleanSelector(),
            **_tuning_schema(cur),
        }
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))

    async def _finish(self):
        return self.async_create_entry(data={**self._data, CONF_ROOMS: self._rooms})
