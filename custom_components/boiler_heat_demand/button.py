"""Reset learning button."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory

from . import device_info
from .const import DOMAIN


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    controller = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            ResetLearningButton(controller, entry),
            BoilerOnButton(controller, entry),
            BoilerOffButton(controller, entry),
            ResumeAutomaticButton(controller, entry),
        ]
    )


class ResetLearningButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "Reset learning"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, controller, entry: ConfigEntry) -> None:
        self._controller = controller
        self._attr_unique_id = f"{entry.entry_id}_reset_learning"
        self._attr_device_info = device_info(entry)

    async def async_press(self) -> None:
        await self._controller.async_reset_learning()


class BoilerOnButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "Boiler on"

    def __init__(self, controller, entry: ConfigEntry) -> None:
        self._controller = controller
        self._attr_unique_id = f"{entry.entry_id}_boiler_on"
        self._attr_device_info = device_info(entry)

    async def async_press(self) -> None:
        await self._controller.async_set_manual_override(True)


class BoilerOffButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "Boiler off"

    def __init__(self, controller, entry: ConfigEntry) -> None:
        self._controller = controller
        self._attr_unique_id = f"{entry.entry_id}_boiler_off"
        self._attr_device_info = device_info(entry)

    async def async_press(self) -> None:
        await self._controller.async_set_manual_override(False)


class ResumeAutomaticButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "Resume automatic control"

    def __init__(self, controller, entry: ConfigEntry) -> None:
        self._controller = controller
        self._attr_unique_id = f"{entry.entry_id}_resume_automatic"
        self._attr_device_info = device_info(entry)

    async def async_press(self) -> None:
        await self._controller.async_resume_automatic()
