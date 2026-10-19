import importlib.util
import pathlib
import sys

spec = importlib.util.spec_from_file_location(
    "learning",
    pathlib.Path(__file__).parent.parent / "custom_components" / "boiler_heat_demand" / "learning.py",
)
learning = importlib.util.module_from_spec(spec)
sys.modules["learning"] = learning
spec.loader.exec_module(learning)
RoomLearner, RoomModel, learned_call, anticipation = (
    learning.RoomLearner, learning.RoomModel, learning.learned_call, learning.anticipation,
)


def simulate(minutes, learner, temp=19.0, target=21.0, use_model=True, outdoor=5.0):
    """Room with thermal lag: radiator keeps delivering heat after the valve closes."""
    calling, radiator, t, peak = False, 0.0, 0.0, temp
    for _ in range(minutes):
        t += 60
        base = temp < target
        calling = learned_call(learner.model, base, calling, temp, target, outdoor, 0.5) if use_model else base
        radiator += ((1.0 if calling else 0.0) - radiator) * 0.1
        temp += (radiator * 3.0 - 0.02 * (temp - outdoor)) / 60
        learner.observe(t, round(temp, 1), target, calling, outdoor, 0.5)
        peak = max(peak, temp)
    return temp, peak


def test_not_ready_follows_base():
    m = RoomModel()
    assert learned_call(m, True, False, 20.0, 21.0, None, 0.5) is True
    assert learned_call(m, False, False, 20.0, 21.0, None, 0.5) is False


def test_early_stop_and_no_flapping():
    m = RoomModel(heat_rate=1.0, cycles=5, coast_rise=0.6)
    assert not learned_call(m, True, True, 20.5, 21.0, None, 0.5)  # 20.5 + 0.6 >= 21
    # right after stopping it must not restart immediately
    assert not learned_call(m, False, False, 20.5, 21.0, None, 0.5)
    assert learned_call(m, False, False, 20.0, 21.0, None, 0.5)


def test_prestart_uses_cooling_and_lag():
    m = RoomModel(heat_rate=1.0, cycles=5, cool_rate=1.0, lag_min=30)
    # 20.6 now, will have cooled 0.5 degC by the time heat arrives -> start
    assert learned_call(m, False, False, 20.6, 21.0, None, 0.4)
    assert not learned_call(RoomModel(heat_rate=1.0, cycles=5, cool_rate=0.0), False, False, 20.6, 21.0, None, 0.4)


def test_learns_and_reduces_overshoot():
    learner = RoomLearner()
    _, peak_naive = simulate(600, RoomLearner(), use_model=False)
    simulate(1500, learner)
    assert learner.model.cycles >= 3
    assert learner.model.heat_rate and learner.model.coast_rise > 0
    learner2 = RoomLearner(model=learner.model)
    _, peak_learned = simulate(600, learner2, temp=19.0)
    assert peak_learned < peak_naive - 0.1


def test_model_roundtrip():
    m = RoomModel(heat_rate=1.2, cycles=4, coast_rise=0.5)
    assert RoomModel.from_dict(m.to_dict()) == m
    assert anticipation(m) == 0.5
