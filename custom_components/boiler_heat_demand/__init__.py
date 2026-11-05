"""Boiler Heat Demand integration."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.typing import ConfigType

from .const import CONF_RELAY, DOMAIN, PLATFORMS
from .controller import BoilerController

_LOGGER = logging.getLogger(__name__)

CARD_FILE = Path(__file__).parent / "frontend" / "boiler-heat-demand-card.js"
CARD_URL = f"/{DOMAIN}/boiler-heat-demand-card.js"


def device_info(entry: ConfigEntry) -> DeviceInfo:
    """All entities of one config entry belong to a single 'Automated Boiler' device."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Automated Boiler",
        manufacturer="bartosekpetr",
        model="Boiler Heat Demand",
    )


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the dashboard card once per Home Assistant start.

    Registering a static path twice raises, so this must not live in
    async_setup_entry, which runs again on every config entry reload.
    """
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(CARD_FILE), cache_headers=False)]
    )
    add_extra_js_url(hass, CARD_URL)
    return True


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


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Nothing manages the relay once the integration is deleted, so do not leave it calling for heat.

    Only deletion does this; reloads (e.g. after changing options) keep the relay as it is.
    """
    relay = {**entry.data, **entry.options}.get(CONF_RELAY)
    state = hass.states.get(relay) if relay else None
    if state is None or state.state != STATE_ON:
        return
    try:
        await hass.services.async_call(
            "switch" if relay.startswith("switch.") else "homeassistant",
            "turn_off",
            {"entity_id": relay},
            blocking=True,
        )
    except Exception as err:  # noqa: BLE001 - removal must still complete
        _LOGGER.error(
            "Could not turn off %s while removing the integration: %s", relay, err
        )
