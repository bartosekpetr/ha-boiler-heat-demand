"""Per-room thermal learning. Pure logic, no Home Assistant imports.

Each room learns, from its own temperature readings:
- heat_rate: rise in degC/h while the boiler is heating it
- cool_rate / cool_coeff: fall in degC/h (and per degC above outdoor) while idle
- coast_rise: how far the room keeps rising after demand stops
- lag_min: minutes between heating starting and the room starting to rise
- start_adj / stop_bias: slow self-tuning nudges from observed under/overshoot
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

MIN_WINDOW_S = 900  # rate samples span at least 15 min (sensors are coarse)
MAX_WINDOW_S = 7200
COAST_MAX_S = 3600
ALPHA = 0.2
READY_CYCLES = 3
STEP = 0.1
OVERSHOOT_TOLERANCE = 0.3
MAX_ANTICIPATION = 2.0


def _ewma(old: float | None, new: float, alpha: float = ALPHA) -> float:
    return new if old is None else old + alpha * (new - old)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass
class RoomModel:
    heat_rate: float | None = None
    cool_rate: float | None = None
    cool_coeff: float | None = None
    coast_rise: float = 0.0
    overshoot: float = 0.0
    lag_min: float = 10.0
    start_adj: float = 0.0
    stop_bias: float = 0.0
    cycles: int = 0

    @property
    def ready(self) -> bool:
        return self.cycles >= READY_CYCLES and self.heat_rate is not None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "RoomModel":
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


def predicted_cool_rate(model: RoomModel, temp: float, outdoor: float | None) -> float:
    """Expected fall in degC/h while idle (>= 0)."""
    if outdoor is not None and model.cool_coeff is not None:
        return max(0.0, model.cool_coeff * (temp - outdoor))
    return max(0.0, model.cool_rate or 0.0)


def anticipation(model: RoomModel) -> float:
    """Degrees before target at which heating should stop."""
    return _clamp(model.coast_rise + model.stop_bias, 0.0, MAX_ANTICIPATION)


def learned_call(
    model: RoomModel,
    base_calling: bool,
    currently_calling: bool,
    temp: float,
    target: float,
    outdoor: float | None,
    start_deficit: float,
) -> bool:
    """Refine the base demand with the learned model.

    - Early stop: stop once temp + expected coast rise reaches the target.
    - Pre-start: start when the temperature predicted after the heating lag
      is below target - start threshold.
    The start threshold is always above the stop anticipation so the room
    cannot flap between the two.
    """
    if not model.ready:
        return base_calling
    stop_at = anticipation(model)
    if base_calling and temp + stop_at >= target:
        return False
    if currently_calling and base_calling:
        return True
    start_threshold = max(start_deficit + model.start_adj, stop_at + 0.2, 0.2)
    predicted = temp - predicted_cool_rate(model, temp, outdoor) * model.lag_min / 60
    if target - predicted >= start_threshold:
        return True
    return base_calling and target - temp >= start_threshold


@dataclass
class RoomLearner:
    """Transient observation state plus the persistent RoomModel."""

    model: RoomModel = field(default_factory=RoomModel)
    _phase: str | None = None
    _w_t: float = 0.0
    _w_temp: float = 0.0
    _w_target: float | None = None
    _heat_start_t: float = 0.0
    _heat_start_temp: float = 0.0
    _lag_done: bool = True
    _coast: bool = False
    _coast_start_temp: float = 0.0
    _coast_target: float = 0.0
    _coast_start_t: float = 0.0
    _peak: float = 0.0
    _cycle_start_gap: float = 0.0

    def observe(
        self,
        now: float,
        temp: float | None,
        target: float | None,
        heating: bool,
        outdoor: float | None,
        start_deficit: float,
    ) -> None:
        """Feed one reading. `heating` is True while the boiler is on and the room is calling."""
        if temp is None or target is None:
            self._reset_window()
            return
        phase = "heat" if heating else "idle"

        if self._coast:
            self._peak = max(self._peak, temp)
            if (
                phase == "heat"
                or temp <= self._peak - 0.2
                or now - self._coast_start_t >= COAST_MAX_S
            ):
                self._finish_coast(start_deficit)

        if phase != self._phase or target != self._w_target:
            if self._phase == "heat" and phase == "idle" and target == self._w_target:
                self._coast = True
                self._coast_start_temp = temp
                self._coast_target = target
                self._coast_start_t = now
                self._peak = temp
            if phase == "heat" and self._phase != "heat":
                self._heat_start_t = now
                self._heat_start_temp = temp
                self._lag_done = False
                self._cycle_start_gap = target - temp
            self._phase = phase
            self._w_t, self._w_temp, self._w_target = now, temp, target
            return

        if phase == "heat" and not self._lag_done and temp >= self._heat_start_temp + 0.1:
            self.model.lag_min = _clamp(
                _ewma(self.model.lag_min, (now - self._heat_start_t) / 60), 1.0, 60.0
            )
            self._lag_done = True

        elapsed = now - self._w_t
        if elapsed < MIN_WINDOW_S:
            return
        if elapsed <= MAX_WINDOW_S:
            rate = (temp - self._w_temp) / (elapsed / 3600)
            self._learn_rate(phase, rate, temp, outdoor)
        self._w_t, self._w_temp = now, temp

    def _learn_rate(self, phase: str, rate: float, temp: float, outdoor: float | None) -> None:
        m = self.model
        if phase == "heat" and 0.05 <= rate <= 10:
            m.heat_rate = _ewma(m.heat_rate, rate)
        elif phase == "idle" and not self._coast and -5 <= rate <= 0.02:
            fall = max(0.0, -rate)
            m.cool_rate = _ewma(m.cool_rate, fall)
            if outdoor is not None and temp - outdoor >= 3:
                m.cool_coeff = _ewma(m.cool_coeff, fall / (temp - outdoor))

    def _finish_coast(self, start_deficit: float) -> None:
        m = self.model
        self._coast = False
        rise = max(0.0, self._peak - self._coast_start_temp)
        over = max(0.0, self._peak - self._coast_target)
        m.coast_rise = _clamp(_ewma(m.coast_rise if m.cycles else None, rise), 0.0, MAX_ANTICIPATION)
        m.overshoot = _ewma(m.overshoot if m.cycles else None, over)
        m.cycles += 1
        # Overshot despite early stop: stop earlier. Never reached target: stop later.
        if over > OVERSHOOT_TOLERANCE:
            m.stop_bias = _clamp(m.stop_bias + STEP, -0.5, 1.0)
        elif self._coast_target - self._peak > OVERSHOOT_TOLERANCE:
            m.stop_bias = _clamp(m.stop_bias - STEP, -0.5, 1.0)
        # Heating started well below the intended threshold: start earlier.
        if self._cycle_start_gap > start_deficit + m.start_adj + OVERSHOOT_TOLERANCE:
            m.start_adj = _clamp(m.start_adj - STEP, -0.3, 1.0)
        elif m.overshoot <= OVERSHOOT_TOLERANCE / 2 and self._cycle_start_gap < start_deficit:
            m.start_adj = _clamp(m.start_adj + STEP / 2, -0.3, 1.0)

    def _reset_window(self) -> None:
        self._phase = None
        self._coast = False
