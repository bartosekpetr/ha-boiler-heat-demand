"""Resolve valve devices to their climate and PID demand entities."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .demand import find_pid_entity


def climate_entities_for_devices(hass: HomeAssistant, device_ids: list[str]) -> tuple[list[str], list[str]]:
    """Return (climate entity ids, device ids that have no climate entity)."""
    registry = er.async_get(hass)
    climates: list[str] = []
    without_climate: list[str] = []
    for device_id in device_ids:
        found = [
            entry.entity_id
            for entry in er.async_entries_for_device(registry, device_id)
            if entry.domain == "climate"
        ]
        if found:
            climates.extend(found)
        else:
            without_climate.append(device_id)
    return climates, without_climate


def split_valves_by_device(hass: HomeAssistant, entity_ids: list[str]) -> tuple[list[str], list[str]]:
    """Return (device ids, climate entities that do not belong to a device)."""
    registry = er.async_get(hass)
    devices: list[str] = []
    orphans: list[str] = []
    for entity_id in entity_ids:
        entry = registry.async_get(entity_id)
        if entry is not None and entry.device_id:
            if entry.device_id not in devices:
                devices.append(entry.device_id)
        else:
            orphans.append(entity_id)
    return devices, orphans


def pid_entity_for_climate(hass: HomeAssistant, climate_entity_id: str) -> str | None:
    """Find the PID heating demand sensor on the same device as a climate entity."""
    registry = er.async_get(hass)
    climate = registry.async_get(climate_entity_id)
    if climate is None or not climate.device_id:
        return None
    return find_pid_entity(
        {
            "entity_id": entry.entity_id,
            "translation_key": entry.translation_key,
            "name": entry.original_name or entry.name,
            "unique_id": entry.unique_id,
            "unit": entry.unit_of_measurement,
        }
        for entry in er.async_entries_for_device(registry, climate.device_id)
        if entry.domain == "sensor"
    )
