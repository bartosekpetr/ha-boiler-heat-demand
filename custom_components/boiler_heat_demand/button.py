"""Reset learning button."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    async_add_entities([ResetLearningButton(hass.data[DOMAIN][entry.entry_id], entry)])


class ResetLearningButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "Reset learning"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, controller, entry: ConfigEntry) -> None:
        self._controller = controller
        self._attr_unique_id = f"{entry.entry_id}_reset_learning"

    async def async_press(self) -> None:
        await self._controller.async_reset_learning()
