"""Boiler Heat Demand integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, PLATFORMS
from .controller import BoilerController


def device_info(entry: ConfigEntry) -> DeviceInfo:
    """All entities of one config entry belong to a single 'Automated Boiler' device."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Automated Boiler",
        manufacturer="bartosekpetr",
        model="Boiler Heat Demand",
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    controller = BoilerController(hass, entry)
    await controller.async_load()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = controller
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    controller.start()
    entry.async_on_unload(entry.add_update_listener(_reload))
    return True


async def _reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id).stop()
    return unloaded
