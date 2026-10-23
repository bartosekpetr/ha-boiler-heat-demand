from datetime import datetime, timezone
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

if sys.platform == "win32":
    pytest.skip("Home Assistant integration tests run on Linux in CI", allow_module_level=True)

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.boiler_heat_demand import device_info
from custom_components.boiler_heat_demand.binary_sensor import HeatDemandSensor
from custom_components.boiler_heat_demand.button import (
    BoilerOffButton,
    BoilerOnButton,
    ResetLearningButton,
    ResumeAutomaticButton,
)
from custom_components.boiler_heat_demand.const import DOMAIN
from custom_components.boiler_heat_demand.controller import BoilerController
from custom_components.boiler_heat_demand.demand import Decision
from custom_components.boiler_heat_demand.devices import (
    climate_entities_for_devices,
    pid_entity_for_climate,
    split_valves_by_device,
)
from custom_components.boiler_heat_demand.sensor import (
    CallingValvesSensor,
    CumulativePidDemandSensor,
    CumulativeTemperatureDeltaSensor,
    LearningSensor,
    MaximumPidDemandSensor,
    TemperatureDeficitSensor,
)


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_controller_auto_detects_pid_attribute(hass):
    hass.states.async_set(
        "climate.living_room",
        "heat",
        {
            "hvac_action": "idle",
            "current_temperature": 20,
            "temperature": 21,
            "pi_heating_demand": 42.5,
        },
    )
    controller = object.__new__(BoilerController)
    controller.hass = hass

    snapshot = controller._snapshot(
        "climate.living_room", datetime.now(timezone.utc), 0, None
    )

    assert snapshot.available
    assert snapshot.pid_demand == 42.5
    assert snapshot.pid_source == "pi_heating_demand"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_controller_legacy_attribute_overrides_detection(hass):
    hass.states.async_set(
        "climate.living_room",
        "heat",
        {"pi_heating_demand": 10, "custom_output": 60},
    )
    controller = object.__new__(BoilerController)
    controller.hass = hass

    snapshot = controller._snapshot(
        "climate.living_room", datetime.now(timezone.utc), 0, "custom_output"
    )

    assert snapshot.pid_demand == 60
    assert snapshot.pid_source == "custom_output"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_controller_ignores_valves_without_pid_attribute(hass):
    controller = object.__new__(BoilerController)
    controller.hass = hass
    for attrs in ({}, {"pid": "not-a-number"}, {"pid": -1}, {"pid": 101}):
        hass.states.async_set("climate.living_room", "heat", attrs)
        snapshot = controller._snapshot(
            "climate.living_room", datetime.now(timezone.utc), 0, None
        )
        assert snapshot.pid_demand is None
        assert snapshot.pid_source is None


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_pid_demand_drives_relay_and_diagnostic_value(hass):
    hass.states.async_set("switch.boiler", "off")
    hass.states.async_set(
        "climate.living_room",
        "heat",
        {
            "hvac_action": "idle",
            "current_temperature": 20,
            "temperature": 21,
            "pi_heating_demand": 35,
        },
    )
    hass.states.async_set(
        "climate.bedroom",
        "heat",
        {
            "hvac_action": "idle",
            "current_temperature": 19.5,
            "temperature": 21,
            "valve_position": 20,
        },
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "relay_entity": "switch.boiler",
            "valve_entities": ["climate.living_room", "climate.bedroom"],
            "demand_mode": "pid_demand",
            "pid_start_percent": 20,
            "pid_stop_percent": 5,
            "learning_enabled": False,
            "valve_timeout_minutes": 0,
        },
    )
    controller = BoilerController(hass, entry)
    controller._command = AsyncMock()

    await controller.async_evaluate()

    assert controller.pid_sources == {
        "climate.living_room": "pi_heating_demand",
        "climate.bedroom": "valve_position",
    }
    assert controller.max_pid_demand == 35
    assert controller.cumulative_pid_demand == 55
    assert controller.max_deficit == 1.5
    assert controller.cumulative_temp_delta == 2.5
    assert controller.decision.demand
    controller._command.assert_awaited_once_with("switch.boiler", True)

    hass.states.async_set("switch.boiler", "on")
    hass.states.async_set(
        "climate.living_room",
        "heat",
        {
            "hvac_action": "idle",
            "current_temperature": 21.5,
            "temperature": 21,
            "pi_heating_demand": 4,
        },
    )
    hass.states.async_set(
        "climate.bedroom",
        "heat",
        {
            "hvac_action": "idle",
            "current_temperature": 20.5,
            "temperature": 21,
            "valve_position": 2,
        },
    )
    await controller.async_evaluate()

    assert not controller.decision.demand
    assert controller.max_pid_demand == 4
    assert controller.cumulative_pid_demand == 6
    assert controller.cumulative_temp_delta == 0.5
    controller._command.assert_awaited_with("switch.boiler", False)


def _register_valve_device(hass, name, with_pid_sensor=True):
    """Create a device shaped like the ZHA iTRV: climate + HVAC action + PI heating demand."""
    from homeassistant.helpers import device_registry as dr, entity_registry as er

    entry = MockConfigEntry(domain="zha")
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("zha", name)},
        name=name,
    )
    registry = er.async_get(hass)
    object_id = name.lower().replace(" ", "_")
    climate = registry.async_get_or_create(
        "climate", "zha", f"{name}-climate", suggested_object_id=object_id,
        device_id=device.id, config_entry=entry,
    )
    registry.async_get_or_create(
        "sensor", "zha", f"{name}-hvac_action", suggested_object_id=f"{object_id}_hvac_action",
        device_id=device.id, config_entry=entry, original_name="HVAC action",
    )
    pid = None
    if with_pid_sensor:
        pid = registry.async_get_or_create(
            "sensor", "zha", f"{name}-pi_heating_demand",
            suggested_object_id=f"{object_id}_pi_heating_demand",
            device_id=device.id, config_entry=entry, original_name="Pi heating demand",
            unit_of_measurement="%",
        )
    return device, climate.entity_id, pid.entity_id if pid else None


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_device_resolves_to_climate_and_pid_sensor(hass):
    device, climate, pid = _register_valve_device(hass, "Chodba vstup")
    other_device, other_climate, _ = _register_valve_device(hass, "Loznice", with_pid_sensor=False)

    assert climate == "climate.chodba_vstup"
    assert pid == "sensor.chodba_vstup_pi_heating_demand"
    assert climate_entities_for_devices(hass, [device.id, other_device.id]) == (
        [climate, other_climate],
        [],
    )
    assert pid_entity_for_climate(hass, climate) == pid
    assert pid_entity_for_climate(hass, other_climate) is None
    assert pid_entity_for_climate(hass, "climate.not_in_the_registry") is None


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_split_valves_by_device_keeps_legacy_climate_entities(hass):
    device, climate, _ = _register_valve_device(hass, "Chodba vstup")

    devices, others = split_valves_by_device(hass, [climate, "climate.generic_thermostat"])

    assert devices == [device.id]
    assert others == ["climate.generic_thermostat"]


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_pid_sensor_of_the_device_drives_a_legacy_climate_only_entry(hass):
    _, climate, pid = _register_valve_device(hass, "Chodba vstup")
    hass.states.async_set("switch.boiler", "off")
    hass.states.async_set(
        climate,
        "heat",
        {"hvac_action": "idle", "current_temperature": 20, "temperature": 21},
    )
    hass.states.async_set(pid, "39", {"unit_of_measurement": "%"})
    # Entry as created by earlier versions: only climate entity ids, no device or PID settings.
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "relay_entity": "switch.boiler",
            "valve_entities": [climate],
            "demand_mode": "pid_demand",
            "pid_start_percent": 20,
            "pid_stop_percent": 5,
            "learning_enabled": False,
            "valve_timeout_minutes": 0,
        },
    )
    controller = BoilerController(hass, entry)
    controller._command = AsyncMock()

    await controller.async_evaluate()

    assert controller.pid_sources == {climate: pid}
    assert controller.max_pid_demand == 39
    controller._command.assert_awaited_once_with("switch.boiler", True)

    hass.states.async_set(pid, "unavailable")
    await controller.async_evaluate()
    assert controller.pid_sources == {}
    assert controller.max_pid_demand is None


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_climate_attribute_is_used_when_the_device_has_no_pid_sensor(hass):
    _, climate, pid = _register_valve_device(hass, "Loznice", with_pid_sensor=False)
    assert pid is None
    hass.states.async_set(
        climate, "heat", {"current_temperature": 20, "temperature": 21, "pi_heating_demand": 47}
    )
    controller = object.__new__(BoilerController)
    controller.hass = hass

    snapshot = controller._snapshot(
        climate, datetime.now(timezone.utc), 0, None, controller._pid_entity(climate)
    )

    assert snapshot.pid_demand == 47
    assert snapshot.pid_source == "pi_heating_demand"


def test_entities_share_the_automated_boiler_device():
    entry = MockConfigEntry(domain=DOMAIN, entry_id="test-entry")
    controller = SimpleNamespace(
        decision=Decision(False, False, ()),
        learners={},
        max_pid_demand=40,
        cumulative_pid_demand=90,
        cumulative_temp_delta=2.5,
    )
    maximum_pid = MaximumPidDemandSensor(controller, entry)
    cumulative_pid = CumulativePidDemandSensor(controller, entry)
    cumulative_delta = CumulativeTemperatureDeltaSensor(controller, entry)
    entities = [
        HeatDemandSensor(controller, entry),
        CallingValvesSensor(controller, entry),
        LearningSensor(controller, entry),
        TemperatureDeficitSensor(controller, entry),
        maximum_pid,
        cumulative_pid,
        cumulative_delta,
        ResetLearningButton(controller, entry),
        BoilerOnButton(controller, entry),
        BoilerOffButton(controller, entry),
        ResumeAutomaticButton(controller, entry),
    ]

    expected = device_info(entry)
    assert expected["name"] == "Automated Boiler"
    assert all(entity._attr_device_info == expected for entity in entities)
    assert maximum_pid.native_value == 40
    assert cumulative_pid.native_value == 90
    assert cumulative_delta.native_value == 2.5
