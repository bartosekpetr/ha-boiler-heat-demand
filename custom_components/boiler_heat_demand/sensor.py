"""Number of valves calling for heat."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory

from . import device_info
from .const import DOMAIN


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    async_add_entities(
        [
            CallingValvesSensor(hass.data[DOMAIN][entry.entry_id], entry),
            LearningSensor(hass.data[DOMAIN][entry.entry_id], entry),
            TemperatureDeficitSensor(hass.data[DOMAIN][entry.entry_id], entry),
            MaximumPidDemandSensor(hass.data[DOMAIN][entry.entry_id], entry),
            CumulativePidDemandSensor(hass.data[DOMAIN][entry.entry_id], entry),
            CumulativeTemperatureDeltaSensor(hass.data[DOMAIN][entry.entry_id], entry),
        ]
    )


class LearningSensor(SensorEntity):
    """Number of rooms with a trained thermal model; per-room details as attributes."""

    _attr_has_entity_name = True
    _attr_name = "Rooms learned"
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, controller, entry: ConfigEntry) -> None:
        self._controller = controller
        self._attr_unique_id = f"{entry.entry_id}_learning"
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._controller.add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> int:
        return sum(1 for r in self._controller.learners.values() if r.model.ready)

    @property
    def extra_state_attributes(self) -> dict:
        return {
            entity_id: {
                "ready": r.model.ready,
                "cycles": r.model.cycles,
                "heat_rate_c_per_h": _round(r.model.heat_rate),
                "cool_rate_c_per_h": _round(r.model.cool_rate),
                "coast_rise_c": _round(r.model.coast_rise),
                "overshoot_c": _round(r.model.overshoot),
                "lag_min": _round(r.model.lag_min, 1),
                "start_adjust_c": _round(r.model.start_adj),
                "stop_bias_c": _round(r.model.stop_bias),
            }
            for entity_id, r in self._controller.learners.items()
        }


def _round(value, digits: int = 2):
    return None if value is None else round(value, digits)


class CallingValvesSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Rooms calling for heat"
    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, controller, entry: ConfigEntry) -> None:
        self._controller = controller
        self._attr_unique_id = f"{entry.entry_id}_calling"
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._controller.add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> int:
        return len(self._controller.decision.calling)


class TemperatureDeficitSensor(SensorEntity):
    """Largest room temperature deficit used by heat-demand calculations."""

    _attr_has_entity_name = True
    _attr_name = "Maximum room temperature deficit"
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, controller, entry: ConfigEntry) -> None:
        self._controller = controller
        self._attr_unique_id = f"{entry.entry_id}_temperature_deficit"
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._controller.add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> float | None:
        return _round(self._controller.max_deficit)

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "demand_mode": self._controller.demand_mode,
            "effective_temperature_deficit": _round(self._controller.effective_deficit),
            "start_deficit": self._controller.start_deficit,
            "stop_deficit": self._controller.stop_deficit,
            "manual_override": self._controller.manual_override,
        }


class MaximumPidDemandSensor(SensorEntity):
    """Highest reported PID heat demand among active valves."""

    _attr_has_entity_name = True
    _attr_name = "Maximum PID demand"
    _attr_should_poll = False
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, controller, entry: ConfigEntry) -> None:
        self._controller = controller
        self._attr_unique_id = f"{entry.entry_id}_pid_demand"
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._controller.add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> float | None:
        value = self._controller.max_pid_demand
        return None if value is None else round(value, 1)


class CumulativePidDemandSensor(SensorEntity):
    """Sum of valid PID demand percentages from active valves."""

    _attr_has_entity_name = True
    _attr_name = "Cumulative PID demand"
    _attr_should_poll = False
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, controller, entry: ConfigEntry) -> None:
        self._controller = controller
        self._attr_unique_id = f"{entry.entry_id}_pid_demand_cumulative"
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._controller.add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> float | None:
        value = self._controller.cumulative_pid_demand
        return None if value is None else round(value, 1)


class CumulativeTemperatureDeltaSensor(SensorEntity):
    """Sum of positive target-minus-current temperature deltas across active rooms."""

    _attr_has_entity_name = True
    _attr_name = "Cumulative temperature delta"
    _attr_should_poll = False
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, controller, entry: ConfigEntry) -> None:
        self._controller = controller
        self._attr_unique_id = f"{entry.entry_id}_temp_delta_cumulative"
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._controller.add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> float | None:
        value = self._controller.cumulative_temp_delta
        return None if value is None else round(value, 2)
