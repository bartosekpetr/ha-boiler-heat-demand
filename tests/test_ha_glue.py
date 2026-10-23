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
from custom_components.boiler_heat_demand.sensor import (
    CallingValvesSensor,
    CumulativePidDemandSensor,
    CumulativeTemperatureDeltaSensor,
    LearningSensor,
    MaximumPidDemandSensor,
    TemperatureDeficitSensor,
)


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_controller_reads_configured_pid_attribute(hass):
    hass.states.async_set(
        "climate.living_room",
        "heat",
        {
            "hvac_action": "idle",
            "current_temperature": 20,
            "temperature": 21,
            "pi_output": 42.5,
        },
    )
    controller = object.__new__(BoilerController)
    controller.hass = hass

    snapshot = controller._snapshot(
        "climate.living_room", datetime.now(timezone.utc), 0, "pi_output"
    )

    assert snapshot.available
    assert snapshot.pid_demand == 42.5


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_controller_ignores_invalid_pid_values(hass):
    controller = object.__new__(BoilerController)
    controller.hass = hass
    for value in ("not-a-number", -1, 101):
        hass.states.async_set("climate.living_room", "heat", {"pid": value})
        snapshot = controller._snapshot(
            "climate.living_room", datetime.now(timezone.utc), 0, "pid"
        )
        assert snapshot.pid_demand is None


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
            "pi_output": 35,
        },
    )
    hass.states.async_set(
        "climate.bedroom",
        "heat",
        {
            "hvac_action": "idle",
            "current_temperature": 19.5,
            "temperature": 21,
            "pi_output": 20,
        },
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "relay_entity": "switch.boiler",
            "valve_entities": ["climate.living_room", "climate.bedroom"],
            "demand_mode": "pid_demand",
            "pid_demand_attribute": "pi_output",
            "pid_start_percent": 20,
            "pid_stop_percent": 5,
            "learning_enabled": False,
            "valve_timeout_minutes": 0,
        },
    )
    controller = BoilerController(hass, entry)
    controller._command = AsyncMock()

    await controller.async_evaluate()

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
            "pi_output": 4,
        },
    )
    hass.states.async_set(
        "climate.bedroom",
        "heat",
        {
            "hvac_action": "idle",
            "current_temperature": 20.5,
            "temperature": 21,
            "pi_output": 2,
        },
    )
    await controller.async_evaluate()

    assert not controller.decision.demand
    assert controller.max_pid_demand == 4
    assert controller.cumulative_pid_demand == 6
    assert controller.cumulative_temp_delta == 0.5
    controller._command.assert_awaited_with("switch.boiler", False)


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
