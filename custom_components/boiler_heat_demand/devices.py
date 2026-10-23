"""Resolve valve devices to their climate and PID demand entities."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .demand import find_pid_entity, group_valves_by_area


def valve_area(hass: HomeAssistant, entity_id: str) -> tuple[str, str] | None:
    """(area_id, area name) of a valve: its own area, else the area of its device."""
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None:
        return None
    area_id = entry.area_id
    if not area_id and entry.device_id:
        device = dr.async_get(hass).async_get(entry.device_id)
        area_id = device.area_id if device else None
    area = ar.async_get(hass).async_get_area(area_id) if area_id else None
    return (area.id, area.name) if area else None


def detect_rooms(hass: HomeAssistant, valves: list[str]) -> tuple[list[dict], list[str]]:
    """Group valves by Home Assistant area; returns (rooms, valves that have no area)."""
    return group_valves_by_area(valves, {v: valve_area(hass, v) for v in valves})


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
