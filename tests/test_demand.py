import importlib.util
import pathlib
import sys

spec = importlib.util.spec_from_file_location(
    "demand",
    pathlib.Path(__file__).parent.parent / "custom_components" / "boiler_heat_demand" / "demand.py",
)
demand = importlib.util.module_from_spec(spec)
sys.modules["demand"] = demand
spec.loader.exec_module(demand)
ValveState, valve_calls_for_heat, decide = demand.ValveState, demand.valve_calls_for_heat, demand.decide


def v(**kw):
    base = dict(entity_id="climate.a", available=True, hvac_mode="heat",
                hvac_action=None, current_temp=None, target_temp=None)
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
