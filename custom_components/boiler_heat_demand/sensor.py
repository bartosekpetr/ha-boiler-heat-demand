"""Number of valves calling for heat."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    async_add_entities([CallingValvesSensor(hass.data[DOMAIN][entry.entry_id], entry)])


class CallingValvesSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Valves calling for heat"
    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, controller, entry: ConfigEntry) -> None:
        self._controller = controller
        self._attr_unique_id = f"{entry.entry_id}_calling"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._controller.add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> int:
        return len(self._controller.decision.calling)
