"""Heat demand binary sensor."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    async_add_entities([HeatDemandSensor(hass.data[DOMAIN][entry.entry_id], entry)])


class HeatDemandSensor(BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Heat demand"
    _attr_should_poll = False

    def __init__(self, controller, entry: ConfigEntry) -> None:
        self._controller = controller
        self._attr_unique_id = f"{entry.entry_id}_demand"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._controller.add_listener(self.async_write_ha_state))

    @property
    def is_on(self) -> bool:
        return self._controller.decision.demand

    @property
    def extra_state_attributes(self) -> dict:
        return {"calling_valves": list(self._controller.decision.calling)}
