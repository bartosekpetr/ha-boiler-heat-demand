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
    CONF_USE_DETECTED,
    CONF_HYSTERESIS,
    CONF_LEARNING,
    CONF_MANUAL_TIMEOUT,
    CONF_MIN_OFF,
    CONF_MIN_ON,
    CONF_MIN_VALVES,
    CONF_NOTIFY,
    CONF_OUTDOOR,
    CONF_PID_START,
    CONF_PID_STOP,
    CONF_RELAY,
    CONF_RELAY_TIMEOUT,
    CONF_ROOMS,
    CONF_SAFETY_MIN_TEMP,
    CONF_START_DEFICIT,
    CONF_STOP_DEFICIT,
    CONF_VALVE_FAILSAFE,
    CONF_VALVE_DEVICES,
    CONF_VALVES,
    CONF_VALVE_TIMEOUT,
    DEFAULT_DEMAND_MODE,
    DEFAULT_HYSTERESIS,
    DEFAULT_LEARNING,
    DEFAULT_MANUAL_TIMEOUT,
    DEFAULT_MIN_OFF,
    DEFAULT_MIN_ON,
    DEFAULT_MIN_VALVES,
    DEFAULT_RELAY_TIMEOUT,
    DEFAULT_SAFETY_MIN_TEMP,
    DEFAULT_START_DEFICIT,
    DEFAULT_STOP_DEFICIT,
    DEFAULT_PID_START,
    DEFAULT_PID_STOP,
    DEFAULT_VALVE_FAILSAFE,
    DEFAULT_VALVE_TIMEOUT,
    DOMAIN,
)
from .demand import (
    FAILSAFE_HEAT,
    FAILSAFE_HOLD,
    FAILSAFE_IGNORE,
    MODE_COUNT,
    MODE_DEFICIT,
    MODE_PID,
)
from .devices import climate_entities_for_devices, detect_rooms, split_valves_by_device


def _valve_fields(hass, current_valves: list[str]) -> dict:
    """Valve devices (preferred) plus climate entities that have no device."""
    devices, others = split_valves_by_device(hass, list(current_valves))
    return {
        vol.Optional(CONF_VALVE_DEVICES, description={"suggested_value": devices or None}): selector.DeviceSelector(
            selector.DeviceSelectorConfig(
                multiple=True, entity=selector.EntityFilterSelectorConfig(domain="climate")
            )
        ),
        vol.Optional(CONF_VALVES, description={"suggested_value": others or None}): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="climate", multiple=True)
        ),
    }


def _resolve_valves(hass, user_input: dict[str, Any]) -> str | None:
    """Turn the selected devices into climate entities; returns an error key or None."""
    devices = list(user_input.pop(CONF_VALVE_DEVICES, None) or [])
    others = list(user_input.get(CONF_VALVES) or [])
    climates, without_climate = climate_entities_for_devices(hass, devices)
    if without_climate:
        return "device_without_climate"
    valves = list(dict.fromkeys([*climates, *others]))
    if not valves:
        return "no_valves"
    user_input[CONF_VALVES] = valves
    return None


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
    selector.SelectOptionDict(value=MODE_PID, label="PID heating demand"),
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
        vol.Required(CONF_PID_START, default=d.get(CONF_PID_START, DEFAULT_PID_START)): selector.NumberSelector(
            selector.NumberSelectorConfig(min=0, max=100, step=1, mode="box", unit_of_measurement="%")
        ),
        vol.Required(CONF_PID_STOP, default=d.get(CONF_PID_STOP, DEFAULT_PID_STOP)): selector.NumberSelector(
            selector.NumberSelectorConfig(min=0, max=100, step=1, mode="box", unit_of_measurement="%")
        ),
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
        vol.Required(
            CONF_MANUAL_TIMEOUT,
            default=d.get(CONF_MANUAL_TIMEOUT, DEFAULT_MANUAL_TIMEOUT),
        ): _timeout_minutes(),
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
    """Rooms come from the Home Assistant areas of the valves; the user only confirms them.

    Valves without an area are the only ones the user has to assign by hand.
    """

    _data: dict[str, Any]
    _rooms: list[dict[str, Any]]
    _detected: list[dict[str, Any]]
    _unassigned: list[str]
    _manual_valves: list[str]

    def _valve_label(self, entity_id: str) -> str:
        state = self.hass.states.get(entity_id)
        return (state.attributes.get("friendly_name") if state else None) or entity_id

    async def _start_rooms(self):
        self._rooms = []
        valves = list(self._data[CONF_VALVES])
        self._detected, self._unassigned = detect_rooms(self.hass, valves)
        self._manual_valves = valves
        if self._detected:
            return await self.async_step_confirm_rooms()
        return await self._next_room_step()

    async def async_step_confirm_rooms(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            if user_input.get(CONF_USE_DETECTED, True):
                self._rooms = [dict(room) for room in self._detected]
                self._manual_valves = list(self._unassigned)
            else:
                self._rooms = []
                self._manual_valves = list(self._data[CONF_VALVES])
            return await self._next_room_step()
        rooms = "\n".join(
            f"- **{room['name']}**: " + ", ".join(self._valve_label(v) for v in room["valves"])
            for room in self._detected
        )
        unassigned = ""
        if self._unassigned:
            unassigned = (
                "\n\nNo area assigned (you will be asked where they belong): "
                + ", ".join(self._valve_label(v) for v in self._unassigned)
            )
        return self.async_show_form(
            step_id="confirm_rooms",
            data_schema=vol.Schema(
                {vol.Required(CONF_USE_DETECTED, default=True): selector.BooleanSelector()}
            ),
            description_placeholders={"rooms": rooms, "unassigned": unassigned},
        )

    def _remaining_valves(self) -> list[str]:
        taken = {e for room in self._rooms for e in room[CONF_ROOM_VALVES]}
        return [v for v in self._manual_valves if v not in taken]

    async def _next_room_step(self):
        if not self._remaining_valves():
            return await self._finish()
        return await self.async_step_rooms()

    def _room_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Optional(CONF_ROOM_NAME): selector.TextSelector(),
                vol.Optional(CONF_ROOM_VALVES): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="climate", multiple=True, include_entities=self._remaining_valves()
                    )
                ),
                vol.Optional(CONF_ROOM_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Required(CONF_ADD_ANOTHER, default=False): selector.BooleanSelector(),
            }
        )

    def _rooms_form(self, errors: dict[str, str] | None = None):
        remaining = ", ".join(self._valve_label(v) for v in self._remaining_valves())
        hint = (
            f"These valves have no area in Home Assistant: {remaining}. "
            "Give them a room name, or leave it empty to keep each as its own room. "
            "Assigning an area to the device in Home Assistant lets it be detected automatically."
        )
        return self.async_show_form(
            step_id="rooms",
            data_schema=self._room_schema(),
            errors=errors or {},
            description_placeholders={"hint": hint},
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
            if not errors and (not user_input.get(CONF_ADD_ANOTHER) or not self._remaining_valves()):
                return await self._finish()
            if not errors:
                return self._rooms_form()
        return self._rooms_form(errors)

    async def _finish(self):
        raise NotImplementedError


class BoilerConfigFlow(_RoomsMixin, config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            error = None
            if float(user_input[CONF_PID_START]) < float(user_input[CONF_PID_STOP]):
                error = "invalid_pid_thresholds"
            else:
                error = _resolve_valves(self.hass, user_input)
            if error:
                return self.async_show_form(
                    step_id="user",
                    data_schema=vol.Schema(self._user_schema()),
                    errors={"base": error},
                )
            await self.async_set_unique_id(user_input[CONF_RELAY])
            self._abort_if_unique_id_configured()
            self._data = dict(user_input)
            return await self._start_rooms()
        return self.async_show_form(step_id="user", data_schema=vol.Schema(self._user_schema()))

    def _user_schema(self) -> dict:
        return {
            vol.Required(CONF_RELAY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["switch", "input_boolean"])
            ),
            **_valve_fields(self.hass, []),
            **_tuning_schema({}),
        }

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
            error = None
            if float(user_input[CONF_PID_START]) < float(user_input[CONF_PID_STOP]):
                error = "invalid_pid_thresholds"
            else:
                error = _resolve_valves(self.hass, user_input)
            if error:
                return self.async_show_form(
                    step_id="init",
                    data_schema=vol.Schema(self._options_schema(cur)),
                    errors={"base": error},
                )
            redefine = user_input.pop(CONF_EDIT_ROOMS, False)
            self._data = dict(user_input)
            if redefine:
                return await self._start_rooms()
            self._rooms = cur.get(CONF_ROOMS, [])
            return await self._finish()
        return self.async_show_form(step_id="init", data_schema=vol.Schema(self._options_schema(cur)))

    def _options_schema(self, cur: dict[str, Any]) -> dict:
        return {
            vol.Required(CONF_RELAY, default=cur[CONF_RELAY]): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["switch", "input_boolean"])
            ),
            **_valve_fields(self.hass, cur[CONF_VALVES]),
            vol.Required(CONF_EDIT_ROOMS, default=False): selector.BooleanSelector(),
            **_tuning_schema(cur),
        }

    async def _finish(self):
        return self.async_create_entry(data={**self._data, CONF_ROOMS: self._rooms})
