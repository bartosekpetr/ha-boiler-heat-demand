from datetime import datetime, timedelta, timezone
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

if sys.platform == "win32":
    pytest.skip("Home Assistant integration tests run on Linux in CI", allow_module_level=True)

from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.boiler_heat_demand import async_remove_entry, device_info
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


def _hall_controller(hass, **options):
    """Controller for one room with an external sensor; the relay command is mocked."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "relay_entity": "switch.boiler",
            "valve_entities": ["climate.hall"],
            "rooms": [{"name": "Hall", "valves": ["climate.hall"], "temp_sensor": "sensor.hall_temp"}],
            "learning_enabled": False,
            "valve_timeout_minutes": 0,
            **options,
        },
    )
    controller = BoilerController(hass, entry)
    controller._command = AsyncMock()
    return controller


@pytest.mark.usefixtures("enable_custom_integrations")
@pytest.mark.parametrize("bad_value", ["nan", "inf", "-inf", "999", "garbage"])
async def test_invalid_room_sensor_falls_back_to_valve_and_keeps_frost_protection(hass, bad_value):
    hass.states.async_set("switch.boiler", "off")
    hass.states.async_set(
        "climate.hall", "heat", {"hvac_action": "idle", "current_temperature": 5, "temperature": 21}
    )
    hass.states.async_set("sensor.hall_temp", bad_value, {"unit_of_measurement": "°C"})
    controller = _hall_controller(hass)

    await controller.async_evaluate()

    assert controller.safety_override
    controller._command.assert_awaited_once_with("switch.boiler", True)


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_frost_protection_uses_room_sensor_when_all_valves_are_offline(hass):
    hass.states.async_set("switch.boiler", "off")
    hass.states.async_set("climate.hall", "unavailable")
    hass.states.async_set("sensor.hall_temp", "5.0", {"unit_of_measurement": "°C"})
    controller = _hall_controller(hass)

    await controller.async_evaluate()

    assert controller.safety_override
    controller._command.assert_awaited_once_with("switch.boiler", True)

    hass.states.async_set("sensor.hall_temp", "19.0", {"unit_of_measurement": "°C"})
    await controller.async_evaluate()
    assert not controller.safety_override


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_room_sensor_units_are_converted_and_stale_sensors_ignored(hass):
    controller = _hall_controller(hass)
    hass.states.async_set("sensor.hall_temp", "41", {"unit_of_measurement": "°F"})
    now = datetime.now(timezone.utc)

    assert abs(controller._sensor_temp("sensor.hall_temp", now, 7200) - 5.0) < 1e-9
    assert controller._sensor_temp("sensor.hall_temp", now + timedelta(hours=3), 7200) is None
    assert controller._sensor_temp("sensor.hall_temp", now + timedelta(hours=3), 0) is not None
    hass.states.async_set("sensor.hall_temp", "41", {"unit_of_measurement": "%"})
    assert controller._sensor_temp("sensor.hall_temp") is None


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_valve_temperatures_follow_the_home_assistant_unit_system(hass):
    from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

    hass.config.units = US_CUSTOMARY_SYSTEM
    hass.states.async_set(
        "climate.hall", "heat", {"current_temperature": 68, "temperature": 71.6, "hvac_action": "idle"}
    )
    controller = object.__new__(BoilerController)
    controller.hass = hass

    snapshot = controller._snapshot("climate.hall", datetime.now(timezone.utc), 0, None)

    assert abs(snapshot.current_temp - 20.0) < 1e-9
    assert abs(snapshot.target_temp - 22.0) < 1e-9


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_manual_override_expires(hass):
    hass.states.async_set("switch.boiler", "off")
    hass.states.async_set(
        "climate.hall", "heat", {"hvac_action": "idle", "current_temperature": 20, "temperature": 21}
    )
    hass.states.async_set("sensor.hall_temp", "20", {"unit_of_measurement": "°C"})
    controller = _hall_controller(hass, manual_override_minutes=30)

    await controller.async_set_manual_override(True)
    assert controller.manual_override is True
    assert 0 < controller.manual_override_seconds_left <= 1800
    controller._command.assert_awaited_once_with("switch.boiler", True)

    controller._manual_set_at -= 1801
    await controller.async_evaluate()
    assert controller.manual_override is None
    assert controller.manual_override_seconds_left is None


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_manual_override_can_be_set_never_to_expire(hass):
    hass.states.async_set("switch.boiler", "off")
    hass.states.async_set("climate.hall", "heat", {"hvac_action": "idle"})
    controller = _hall_controller(hass, manual_override_minutes=0)

    await controller.async_set_manual_override(False)
    controller._manual_set_at -= 10**7
    await controller.async_evaluate()

    assert controller.manual_override is False
    assert controller.manual_override_seconds_left is None

    await controller.async_resume_automatic()
    assert controller.manual_override is None


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_evaluation_failure_raises_an_alert_and_recovers(hass):
    hass.states.async_set("switch.boiler", "off")
    controller = _hall_controller(hass)
    controller._raise_alert = MagicMock()
    controller._clear_alert = MagicMock()

    controller._async_evaluate = AsyncMock(side_effect=RuntimeError("boom"))
    await controller.async_evaluate()

    key, message = controller._raise_alert.call_args.args
    assert key == "evaluation_failed" and "boom" in message and "switch.boiler" in message
    controller._clear_alert.assert_not_called()

    controller._async_evaluate = AsyncMock()
    await controller.async_evaluate()
    controller._clear_alert.assert_called_once_with("evaluation_failed")


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_one_failing_entity_does_not_block_the_other_listeners(hass):
    controller = _hall_controller(hass)
    seen = []

    def broken():
        raise RuntimeError("entity gone")

    controller.add_listener(broken)
    controller.add_listener(lambda: seen.append("ok"))

    controller._publish(Decision(False, False, ()))

    assert seen == ["ok"]


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_corrupt_learning_storage_does_not_break_loading(hass):
    controller = _hall_controller(hass)
    controller._store.async_load = AsyncMock(
        return_value={"rooms": {"Hall": {"lag_min": None, "heat_rate": "fast", "cycles": 5}, 7: {}}}
    )

    await controller.async_load()

    assert list(controller.learners) == ["Hall"]
    assert controller.learners["Hall"].model.lag_min == 10.0
    assert controller.learners["Hall"].model.heat_rate is None
    assert controller.learners["Hall"].model.cycles == 5

    for garbage in (None, [], "x", {"rooms": [1, 2]}):
        controller.learners.clear()
        controller._store.async_load = AsyncMock(return_value=garbage)
        await controller.async_load()
        assert controller.learners == {}


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_removing_the_integration_turns_a_running_relay_off(hass):
    calls = async_mock_service(hass, "switch", "turn_off")
    entry = MockConfigEntry(domain=DOMAIN, data={"relay_entity": "switch.boiler"})

    hass.states.async_set("switch.boiler", "off")
    await async_remove_entry(hass, entry)
    assert calls == []

    hass.states.async_set("switch.boiler", "on")
    await async_remove_entry(hass, entry)
    assert [c.data["entity_id"] for c in calls] == ["switch.boiler"]


def _area_valve(hass, name, area_id=None, entity_area_id=None):
    """A climate entity on its own device, optionally with a device area and/or an entity area."""
    from homeassistant.helpers import device_registry as dr, entity_registry as er

    entry = MockConfigEntry(domain="zha")
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("zha", name)}, name=name
    )
    if area_id:
        dr.async_get(hass).async_update_device(device.id, area_id=area_id)
    registry = er.async_get(hass)
    climate = registry.async_get_or_create(
        "climate", "zha", f"{name}-climate", suggested_object_id=name.lower().replace(" ", "_"),
        device_id=device.id, config_entry=entry, has_entity_name=True, original_name="Thermostat",
    )
    if entity_area_id:
        registry.async_update_entity(climate.entity_id, area_id=entity_area_id)
    hass.states.async_set(climate.entity_id, "heat", {"friendly_name": name})
    return climate.entity_id


def _room_flow(hass, valves):
    from custom_components.boiler_heat_demand.config_flow import BoilerConfigFlow

    flow = BoilerConfigFlow()
    flow.hass, flow.handler, flow.flow_id, flow.context = hass, DOMAIN, "test", {"source": "user"}
    flow._data = {"relay_entity": "switch.boiler", "valve_entities": valves}
    return flow


def _offered_valves(form):
    """Entities the room form's valve selector offers."""
    schema = form["data_schema"].schema
    key = next(k for k in schema if str(k) == "valves")
    return schema[key].config["include_entities"]


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_valve_area_and_room_detection(hass):
    from homeassistant.helpers import area_registry as ar

    from custom_components.boiler_heat_demand.devices import detect_rooms, valve_area

    bedroom = ar.async_get(hass).async_create("Ložnice")
    hall = ar.async_get(hass).async_create("Chodba")
    heating = _area_valve(hass, "Ložnice topeni", area_id=bedroom.id)
    window = _area_valve(hass, "Ložnice okno", area_id=bedroom.id)
    entrance = _area_valve(hass, "Chodba vstup", area_id=bedroom.id, entity_area_id=hall.id)
    cellar = _area_valve(hass, "Sklep")

    assert valve_area(hass, heating) == (bedroom.id, "Ložnice")
    assert valve_area(hass, entrance) == (hall.id, "Chodba")  # an entity's own area wins
    assert valve_area(hass, cellar) is None
    assert valve_area(hass, "climate.not_in_the_registry") is None
    rooms, unassigned = detect_rooms(hass, [heating, window, entrance, cellar])
    assert [(r["name"], r["valves"]) for r in rooms] == [
        ("Ložnice", [heating, window]),
        ("Chodba", [entrance]),
    ]
    assert unassigned == [cellar]


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_flow_confirms_detected_rooms_and_only_asks_for_valves_without_an_area(hass):
    from homeassistant.helpers import area_registry as ar

    bedroom = ar.async_get(hass).async_create("Ložnice")
    heating = _area_valve(hass, "Ložnice topeni", area_id=bedroom.id)
    window = _area_valve(hass, "Ložnice okno", area_id=bedroom.id)
    cellar = _area_valve(hass, "Sklep")
    flow = _room_flow(hass, [heating, window, cellar])

    form = await flow._start_rooms()
    assert form["step_id"] == "confirm_rooms"
    assert "**Ložnice**: Ložnice topeni, Ložnice okno" in form["description_placeholders"]["rooms"]
    assert "Sklep" in form["description_placeholders"]["unassigned"]

    form = await flow.async_step_confirm_rooms({"use_detected_rooms": True})
    assert form["step_id"] == "rooms"
    assert _offered_valves(form) == [cellar]
    assert "Sklep" in form["description_placeholders"]["hint"]

    result = await flow.async_step_rooms({"name": "Sklep", "valves": [cellar], "add_another": False})
    assert result["type"].value == "create_entry"
    assert [(r["name"], r["valves"]) for r in result["data"]["rooms"]] == [
        ("Ložnice", [heating, window]),
        ("Sklep", [cellar]),
    ]

    # a hand-made room may not reuse a detected room's name
    flow = _room_flow(hass, [heating, cellar])
    await flow._start_rooms()
    await flow.async_step_confirm_rooms({"use_detected_rooms": True})
    form = await flow.async_step_rooms({"name": "Ložnice", "valves": [cellar], "add_another": False})
    assert form["errors"] == {"base": "room_duplicate"}


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_flow_finishes_after_confirmation_when_every_valve_has_an_area(hass):
    from homeassistant.helpers import area_registry as ar

    bedroom = ar.async_get(hass).async_create("Ložnice")
    hall = ar.async_get(hass).async_create("Chodba")
    heating = _area_valve(hass, "Ložnice topeni", area_id=bedroom.id)
    entrance = _area_valve(hass, "Chodba vstup", area_id=hall.id)
    flow = _room_flow(hass, [heating, entrance])

    await flow._start_rooms()
    result = await flow.async_step_confirm_rooms({"use_detected_rooms": True})

    assert result["type"].value == "create_entry"
    assert [r["name"] for r in result["data"]["rooms"]] == ["Ložnice", "Chodba"]


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_flow_declining_detection_or_having_no_areas_offers_manual_grouping(hass):
    from homeassistant.helpers import area_registry as ar

    bedroom = ar.async_get(hass).async_create("Ložnice")
    heating = _area_valve(hass, "Ložnice topeni", area_id=bedroom.id)
    cellar = _area_valve(hass, "Sklep")

    flow = _room_flow(hass, [heating, cellar])
    await flow._start_rooms()
    form = await flow.async_step_confirm_rooms({"use_detected_rooms": False})
    assert form["step_id"] == "rooms" and _offered_valves(form) == [heating, cellar]

    flow = _room_flow(hass, [cellar])
    form = await flow._start_rooms()
    assert form["step_id"] == "rooms"  # nothing detected: straight to manual grouping
    result = await flow.async_step_rooms({"add_another": False})
    assert result["type"].value == "create_entry" and result["data"]["rooms"] == []


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
