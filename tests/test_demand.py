import importlib.util
import pathlib
import sys
from datetime import datetime, timedelta, timezone

spec = importlib.util.spec_from_file_location(
    "demand",
    pathlib.Path(__file__).parent.parent / "custom_components" / "boiler_heat_demand" / "demand.py",
)
demand = importlib.util.module_from_spec(spec)
sys.modules["demand"] = demand
spec.loader.exec_module(demand)
ValveState, valve_calls_for_heat, decide = demand.ValveState, demand.valve_calls_for_heat, demand.decide
valve_report_is_stale = demand.valve_report_is_stale
demand_met, valve_deficit, valve_is_too_cold = demand.demand_met, demand.valve_deficit, demand.valve_is_too_cold
detect_pid_attribute = demand.detect_pid_attribute
find_pid_entity = demand.find_pid_entity


def ent(entity_id, name=None, translation_key=None, unique_id=None, unit="%"):
    return dict(entity_id=entity_id, name=name, translation_key=translation_key,
                unique_id=unique_id, unit=unit)


def test_find_pid_entity_in_the_chodba_vstup_device():
    # Entities of the ZHA iTRV "Chodba vstup": climate is handled elsewhere.
    entries = [
        ent("climate.chodba_vstup", unit=None),
        ent("sensor.chodba_vstup_hvac_action", "HVAC action", unit=None),
        ent("sensor.chodba_vstup_battery", "Battery"),
        ent("number.chodba_vstup_local_temperature_offset", "Local temperature offset", unit="°C"),
        ent("sensor.chodba_vstup_pi_heating_demand", "Pi heating demand"),
    ]
    assert find_pid_entity(entries) == "sensor.chodba_vstup_pi_heating_demand"


def test_find_pid_entity_survives_renaming_by_using_translation_key_or_name():
    renamed = ent("sensor.hallway_valve_demand", "Pi heating demand")
    assert find_pid_entity([renamed]) == "sensor.hallway_valve_demand"
    keyed = ent("sensor.x", "Whatever", translation_key="pi_heating_demand")
    assert find_pid_entity([keyed]) == "sensor.x"
    by_unique_id = ent("sensor.y", None, unique_id="b4:e3:f9:ff:fe:59:26:97-1-513-pi_heating_demand")
    assert find_pid_entity([by_unique_id]) == "sensor.y"


def test_find_pid_entity_prefers_known_names_then_falls_back_to_hints():
    entries = [ent("sensor.a_heating_demand", "Heating demand"),
               ent("sensor.a_pi_heating_demand", "Pi heating demand")]
    assert find_pid_entity(entries) == "sensor.a_pi_heating_demand"
    assert find_pid_entity([ent("sensor.a_trv_pid_output_percent", "TRV PID output percent")]) == "sensor.a_trv_pid_output_percent"


def test_find_pid_entity_ignores_wrong_units_domains_and_settings():
    assert find_pid_entity([]) is None
    assert find_pid_entity([ent("sensor.a_pi_heating_demand", "Pi heating demand", unit="°C")]) is None
    assert find_pid_entity([ent("number.a_pi_heating_demand", "Pi heating demand")]) is None
    assert find_pid_entity([ent("sensor.a_pid_kp", "PID kp"), ent("sensor.a_battery", "Battery")]) is None
    assert find_pid_entity([ent("sensor.a_pi_heating_demand", "Pi heating demand", unit=None)]) == "sensor.a_pi_heating_demand"


def test_detect_pid_attribute_known_vendor_names():
    assert detect_pid_attribute({"pi_heating_demand": 42}) == ("pi_heating_demand", 42.0)
    assert detect_pid_attribute({"valve_position": "17.5"}) == ("valve_position", 17.5)
    assert detect_pid_attribute({"valve_opening_degree": 0}) == ("valve_opening_degree", 0.0)


def test_detect_pid_attribute_prefers_known_names_over_fuzzy_matches():
    attrs = {"my_pid_value": 80, "pi_heating_demand": 30}
    assert detect_pid_attribute(attrs) == ("pi_heating_demand", 30.0)


def test_detect_pid_attribute_falls_back_to_name_hints():
    assert detect_pid_attribute({"trv_pid_output_percent": 55}) == ("trv_pid_output_percent", 55.0)


def test_detect_pid_attribute_ignores_settings_and_invalid_values():
    attrs = {
        "pid_kp": 40,
        "pid_target_temperature": 21,
        "max_valve_position": 100,
        "temperature": 21,
        "current_temperature": 20,
        "hvac_action": "heating",
        "pi_heating_demand": 101,
        "valve_position": True,
        "heating_demand": "n/a",
    }
    assert detect_pid_attribute(attrs) is None
    assert detect_pid_attribute({}) is None


def v(**kw):
    base = dict(entity_id="climate.a", available=True, hvac_mode="heat",
                hvac_action=None, current_temp=None, target_temp=None, pid_demand=None)
    base.update(kw)
    return ValveState(**base)


def test_action_heating_calls():
    assert valve_calls_for_heat(v(hvac_action="heating"), 0.3, False)
    assert not valve_calls_for_heat(v(hvac_action="idle"), 0.3, False)


def test_off_or_unavailable_never_calls():
    assert not valve_calls_for_heat(v(hvac_mode="off", hvac_action="heating"), 0.3, False)
    assert not valve_calls_for_heat(v(available=False, hvac_action="heating"), 0.3, False)


def test_temperature_fallback_hysteresis():
    cold = v(current_temp=20.0, target_temp=21.0)
    assert valve_calls_for_heat(cold, 0.3, False)
    near = v(current_temp=20.8, target_temp=21.0)
    assert not valve_calls_for_heat(near, 0.3, False)
    assert valve_calls_for_heat(near, 0.3, True)
    assert not valve_calls_for_heat(v(current_temp=21.0, target_temp=21.0), 0.3, True)


def test_min_valves():
    assert not decide(["a"], 2, False, None, 0, 0).demand
    assert decide(["a", "b"], 2, False, None, 0, 0).boiler_on


def test_min_on_and_off_lockout():
    assert decide([], 1, True, 60, 300, 300).boiler_on  # held on
    assert not decide([], 1, True, 400, 300, 300).boiler_on
    assert not decide(["a"], 1, False, 60, 300, 300).boiler_on  # held off
    assert decide(["a"], 1, False, 400, 300, 300).boiler_on


def test_valve_report_timeout():
    now = datetime.now(timezone.utc)
    assert valve_report_is_stale(now - timedelta(seconds=60), now, 60)
    assert not valve_report_is_stale(now - timedelta(seconds=59), now, 60)
    assert valve_report_is_stale(None, now, 60)


def test_valve_report_timeout_can_be_disabled():
    now = datetime.now(timezone.utc)
    assert not valve_report_is_stale(None, now, 0)


def test_deficit_mode_start_stop_hysteresis():
    args = dict(min_valves=1, start_deficit=0.5, stop_deficit=0.1)
    assert not demand_met("temperature_deficit", 0, 0.3, boiler_is_on=False, **args)
    assert demand_met("temperature_deficit", 0, 0.5, boiler_is_on=False, **args)
    assert demand_met("temperature_deficit", 0, 0.3, boiler_is_on=True, **args)  # keeps heating
    assert not demand_met("temperature_deficit", 0, 0.1, boiler_is_on=True, **args)
    assert not demand_met("temperature_deficit", 0, None, boiler_is_on=False, **args)


def test_deficit_mode_failsafe_forces_demand():
    assert demand_met("temperature_deficit", 1, None, 1, 0.5, 0.1, False, failsafe_calling=True)


def test_pid_mode_start_stop_hysteresis():
    args = dict(mode="pid_demand", calling_count=0, max_deficit=None, min_valves=1,
                start_deficit=0.5, stop_deficit=0.1, pid_start=20, pid_stop=5)
    assert not demand_met(**args, boiler_is_on=False, max_pid_demand=19.9)
    assert demand_met(**args, boiler_is_on=False, max_pid_demand=20)
    assert demand_met(**args, boiler_is_on=True, max_pid_demand=5.1)
    assert not demand_met(**args, boiler_is_on=True, max_pid_demand=5)


def test_pid_mode_falls_back_to_valve_calls_without_readings():
    args = dict(mode="pid_demand", max_deficit=None, min_valves=1,
                start_deficit=0.5, stop_deficit=0.1, max_pid_demand=None)
    assert demand_met(**args, calling_count=1, boiler_is_on=False)
    assert not demand_met(**args, calling_count=0, boiler_is_on=False)
    assert demand_met(**args, calling_count=0, boiler_is_on=False, failsafe_calling=True)


def test_valve_deficit_ignores_off_and_unavailable():
    assert valve_deficit(v(current_temp=19.0, target_temp=21.0)) == 2.0
    assert valve_deficit(v(hvac_mode="off", current_temp=19.0, target_temp=21.0)) is None
    assert valve_deficit(v(available=False, current_temp=19.0, target_temp=21.0)) is None


def test_safety_min_temp():
    assert valve_is_too_cold(v(current_temp=7.0), 8.0)
    assert not valve_is_too_cold(v(current_temp=9.0), 8.0)
    assert not valve_is_too_cold(v(current_temp=7.0, hvac_mode="off"), 8.0)
    assert not valve_is_too_cold(v(current_temp=1.0), 0)


def test_safety_force_on_bypasses_min_off_only():
    assert decide([], 1, False, 10, 300, 300, force_on=True).boiler_on
    assert not decide(["a"], 1, False, 10, 300, 300).boiler_on  # normal demand stays locked out
    assert decide([], 1, True, 10, 300, 300, demand=False, force_on=True).boiler_on


def test_manual_override_bypasses_lockouts():
    assert decide([], 1, False, 10, 300, 300, manual_override=True).boiler_on
    assert not decide(["a"], 1, True, 10, 300, 300, manual_override=False).boiler_on


def test_manual_override_does_not_change_calculated_demand():
    decision = decide([], 1, False, None, 0, 0, manual_override=True)
    assert not decision.demand and decision.boiler_on


def test_room_with_two_valves_any_calls():
    room = demand.aggregate_room(
        [v(entity_id="a", hvac_action="idle", current_temp=21.0, target_temp=21.0),
         v(entity_id="b", hvac_action="heating", current_temp=20.0, target_temp=21.0)], 0.3, False)
    assert room.calling and room.available and room.active
    assert room.temp == 20.5 and room.target == 21.0


def test_room_uses_external_sensor_and_highest_target():
    room = demand.aggregate_room(
        [v(entity_id="a", current_temp=24.0, target_temp=21.0),
         v(entity_id="b", current_temp=24.0, target_temp=22.0)], 0.3, False, sensor_temp=20.0)
    assert room.temp == 20.0 and room.target == 22.0 and room.calling  # fallback uses room temp


def test_room_median_ignores_outlier():
    valves = [v(entity_id=str(i), current_temp=t, target_temp=21.0) for i, t in enumerate([20.0, 20.2, 25.0])]
    assert demand.aggregate_room(valves, 0.3, False).temp == 20.2


def test_room_uses_highest_available_pid_demand():
    room = demand.aggregate_room(
        [v(entity_id="a", pid_demand=12.5), v(entity_id="b", pid_demand=45.0),
         v(entity_id="c", pid_demand=None)],
        0.3,
        False,
    )
    assert room.pid_demand == 45.0


def test_room_partial_and_total_failure():
    ok = v(entity_id="a", hvac_action="idle")
    dead = v(entity_id="b", available=False)
    assert demand.aggregate_room([ok, dead], 0.3, False).available
    assert not demand.aggregate_room([dead], 0.3, False).available
    off = demand.aggregate_room([v(hvac_mode="off")], 0.3, False)
    assert off.available and not off.active and not off.calling


def test_build_rooms_groups_and_defaults():
    rooms = demand.build_rooms(
        ["climate.a", "climate.b", "climate.c"],
        [{"name": "Living", "valves": ["climate.a", "climate.b", "climate.x"], "temp_sensor": "sensor.t"}],
    )
    assert [r.name for r in rooms] == ["Living", "climate.c"]
    assert rooms[0].valves == ("climate.a", "climate.b") and rooms[0].sensor == "sensor.t"
    assert demand.build_rooms(["climate.a"], None)[0].valves == ("climate.a",)


NAN, INF, NINF = float("nan"), float("inf"), float("-inf")


def test_parse_temperature_rejects_non_finite_and_implausible_values():
    for bad in ("nan", "inf", "-inf", NAN, INF, NINF, "abc", None, True, 61, -51, 500):
        assert demand.parse_temperature(bad) is None, bad
    assert demand.parse_temperature("21.5") == 21.5
    assert demand.parse_temperature(0) == 0.0
    assert demand.parse_temperature(-50) == -50.0 and demand.parse_temperature(60) == 60.0


def test_parse_temperature_converts_units_and_rejects_unknown_ones():
    assert abs(demand.parse_temperature(68, "°F") - 20.0) < 1e-9
    assert abs(demand.parse_temperature(293.15, "K") - 20.0) < 1e-9
    assert demand.parse_temperature(20, "°C") == 20.0
    assert demand.parse_temperature(20, "%") is None
    assert demand.parse_temperature(5, "m/s") is None
    assert demand.parse_temperature(200, "°F") is None  # 93 degC is implausible


def test_nan_room_sensor_falls_back_to_valve_temperature():
    cold = v(current_temp=5.0, target_temp=21.0)
    room = demand.aggregate_room([cold], 0.3, False, sensor_temp=NAN)
    assert room.temp == 5.0
    assert demand.aggregate_room([cold], 0.3, False, sensor_temp=NINF).temp == 5.0


def test_non_finite_valve_values_never_count_as_heat_demand_or_deficit():
    broken = v(current_temp=NAN, target_temp=21.0)
    assert not valve_calls_for_heat(broken, 0.3, False)
    assert valve_deficit(broken) is None
    assert not valve_is_too_cold(broken, 8.0)
    room = demand.aggregate_room([broken, v(current_temp=19.0, target_temp=NAN)], 0.3, False)
    # only finite values contribute: the temperature comes from one valve, the target from the other
    assert room.temp == 19.0 and room.target == 21.0
    only_nan = demand.aggregate_room([v(current_temp=NAN, target_temp=NAN)], 0.3, False)
    assert only_nan.temp is None and only_nan.target is None


def test_sensor_timeout_is_longer_than_valve_timeout_but_stays_disableable():
    assert demand.sensor_timeout_seconds(0) == 0
    assert demand.sensor_timeout_seconds(1800) == 7200
    assert demand.sensor_timeout_seconds(10800) == 10800


def test_manual_override_expires_after_the_timeout():
    expired = demand.manual_override_expired
    assert not expired(None, 1000.0, 60)
    assert not expired(100.0, 159.0, 60)
    assert expired(100.0, 160.0, 60)
    assert not expired(100.0, 10**9, 0)  # 0 means never
