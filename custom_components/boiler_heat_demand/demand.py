"""Pure heat-demand logic. No Home Assistant imports so it stays unit-testable."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Any, Iterable, Mapping

TEMPERATURE_MIN_C = -50.0
TEMPERATURE_MAX_C = 60.0
# An external room sensor may legitimately report only every hour or two, so it gets a
# longer freshness window than a valve; 0 (staleness disabled) is still honoured.
SENSOR_MIN_TIMEOUT_S = 7200.0


def _finite(value: float | None) -> bool:
    return value is not None and math.isfinite(value)


def parse_temperature(value: Any, unit: str | None = None) -> float | None:
    """Return a plausible temperature in degrees C, or None.

    Rejects booleans, NaN/inf, unknown units and values outside -50..60 degC so a
    faulty or hostile source cannot disable the safety logic or poison learning.
    """
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    if unit in (None, "", "°C", "C", "℃"):
        pass
    elif unit in ("°F", "F"):
        number = (number - 32.0) * 5.0 / 9.0
    elif unit == "K":
        number -= 273.15
    else:
        return None
    return number if TEMPERATURE_MIN_C <= number <= TEMPERATURE_MAX_C else None


def sensor_timeout_seconds(valve_timeout_seconds: float) -> float:
    """Freshness window for external room sensors (0 keeps staleness checks disabled)."""
    if valve_timeout_seconds <= 0:
        return 0.0
    return max(valve_timeout_seconds, SENSOR_MIN_TIMEOUT_S)


def manual_override_expired(
    set_at: float | None, now: float, timeout_seconds: float
) -> bool:
    """True when a manual boiler override has outlived its timeout (0 = never expires)."""
    return timeout_seconds > 0 and set_at is not None and now - set_at >= timeout_seconds

# Well-known TRV attributes that report heating demand / valve opening as 0-100 %.
PID_ATTRIBUTE_CANDIDATES = (
    "pi_heating_demand",
    "pid_heating_demand",
    "pid_demand",
    "pi_demand",
    "pid_output",
    "pi_output",
    "heating_demand",
    "valve_opening_degree",
    "valve_position",
    "valve_opening",
    "valve_open_percent",
    "valve_level",
)
_PID_NAME_HINTS = ("pid", "heating_demand", "heat_demand", "valve_position", "valve_opening")
_PID_NAME_EXCLUDES = (
    "target", "setpoint", "set_point", "offset", "min", "max", "limit", "window",
    "kp", "ki", "kd", "gain", "threshold", "calibration", "mode", "time", "interval",
)


def parse_percentage(value: Any) -> float | None:
    """Return value as a number from 0 to 100, or None if it is not one."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if 0 <= number <= 100 else None


def detect_pid_attribute(attributes: Mapping[str, Any]) -> tuple[str, float] | None:
    """Find the attribute of a valve that reports its PID heating demand.

    Known vendor names win; otherwise attributes whose name looks like a demand or
    valve-opening value are used. Only numeric values from 0 to 100 are accepted.
    """
    for name in PID_ATTRIBUTE_CANDIDATES:
        value = parse_percentage(attributes.get(name))
        if value is not None:
            return name, value
    for name in sorted(attributes):
        lowered = str(name).lower()
        if not any(hint in lowered for hint in _PID_NAME_HINTS):
            continue
        if any(excluded in lowered for excluded in _PID_NAME_EXCLUDES):
            continue
        value = parse_percentage(attributes[name])
        if value is not None:
            return str(name), value
    return None


def _normalize(text: Any) -> str:
    return "_".join(str(text or "").lower().replace("-", "_").split())


def _name_matches(key: str, candidate: str) -> bool:
    return key == candidate or key.endswith("_" + candidate)


def find_pid_entity(entries: Iterable[Mapping[str, Any]]) -> str | None:
    """Pick the sensor that reports PID heating demand from a device's entities.

    Each entry needs ``entity_id`` and may have ``translation_key``, ``name``,
    ``unique_id`` and ``unit``. Sensors with a known demand name win in the order of
    ``PID_ATTRIBUTE_CANDIDATES``; otherwise names that look like a demand are used.
    Sensors measured in anything but percent are ignored.
    """
    best: tuple[int, str] | None = None
    for entry in entries:
        entity_id = str(entry.get("entity_id") or "")
        if not entity_id.startswith("sensor."):
            continue
        unit = entry.get("unit")
        if unit not in (None, "%"):
            continue
        keys = {
            _normalize(entry.get("translation_key")),
            _normalize(entry.get("name")),
            _normalize(entity_id.split(".", 1)[1]),
            _normalize(entry.get("unique_id")),
        }
        keys.discard("")
        score = 0
        for rank, candidate in enumerate(PID_ATTRIBUTE_CANDIDATES):
            if any(_name_matches(key, candidate) for key in keys):
                score = 1000 - rank
                break
        if not score:
            fuzzy = [
                key
                for key in keys
                if any(hint in key for hint in _PID_NAME_HINTS)
                and not any(excluded in key for excluded in _PID_NAME_EXCLUDES)
            ]
            if fuzzy:
                score = 1
        if score and (
            best is None or score > best[0] or (score == best[0] and entity_id < best[1])
        ):
            best = (score, entity_id)
    return best[1] if best else None


def valve_report_is_stale(
    last_reported: datetime | None,
    now: datetime,
    timeout_seconds: float,
) -> bool:
    """Return True when a valve has not reported within the configured timeout."""
    if timeout_seconds <= 0:
        return False
    if last_reported is None:
        return True
    return (now - last_reported).total_seconds() >= timeout_seconds


@dataclass(frozen=True)
class ValveState:
    """Snapshot of one thermostatic valve."""

    entity_id: str
    available: bool
    hvac_mode: str | None
    hvac_action: str | None
    current_temp: float | None
    target_temp: float | None
    pid_demand: float | None = None
    pid_source: str | None = None


def valve_calls_for_heat(valve: ValveState, hysteresis: float, currently_calling: bool) -> bool:
    """Return True if the valve wants heat.

    Prefers the valve's own hvac_action. Falls back to temperatures with
    hysteresis (start below target - hysteresis, stop at target) when the
    valve does not report an action.
    """
    if not valve.available or valve.hvac_mode in (None, "off"):
        return False
    if valve.hvac_action is not None:
        return valve.hvac_action == "heating"
    if not _finite(valve.current_temp) or not _finite(valve.target_temp):
        return False
    if currently_calling:
        return valve.current_temp < valve.target_temp
    return valve.current_temp <= valve.target_temp - hysteresis


MODE_COUNT = "valve_count"
MODE_DEFICIT = "temperature_deficit"
MODE_PID = "pid_demand"

FAILSAFE_IGNORE = "ignore"
FAILSAFE_HEAT = "call_for_heat"
FAILSAFE_HOLD = "hold_last"


def valve_deficit(valve: ValveState) -> float | None:
    """Degrees below target for a valve that is available and not off, else None."""
    if not valve.available or valve.hvac_mode in (None, "off"):
        return None
    if not _finite(valve.current_temp) or not _finite(valve.target_temp):
        return None
    return valve.target_temp - valve.current_temp


def valve_is_too_cold(valve: ValveState, safety_min_temp: float) -> bool:
    """True when an active valve's room is at or below the safety temperature (0 disables)."""
    if safety_min_temp <= 0 or not valve.available or valve.hvac_mode in (None, "off"):
        return False
    return _finite(valve.current_temp) and valve.current_temp <= safety_min_temp


def demand_met(
    mode: str,
    calling_count: int,
    max_deficit: float | None,
    min_valves: int,
    start_deficit: float,
    stop_deficit: float,
    boiler_is_on: bool,
    failsafe_calling: bool = False,
    max_pid_demand: float | None = None,
    pid_start: float = 20.0,
    pid_stop: float = 5.0,
) -> bool:
    """Evaluate demand by valve count, largest deficit, or highest PID demand.

    Deficit mode uses separate start/stop thresholds (start >= stop) so the
    boiler does not toggle around a single value. PID mode uses the same
    hysteresis and falls back to valve count when no valid PID value is reported.
    """
    if mode == MODE_DEFICIT:
        if failsafe_calling:
            return True
        if max_deficit is None:
            return False
        if boiler_is_on:
            return max_deficit > stop_deficit
        return max_deficit >= start_deficit
    if mode == MODE_PID:
        if failsafe_calling:
            return True
        if max_pid_demand is None:
            return calling_count >= min_valves
        if boiler_is_on:
            return max_pid_demand > pid_stop
        return max_pid_demand >= pid_start
    return calling_count >= min_valves


@dataclass(frozen=True)
class Decision:
    demand: bool
    boiler_on: bool
    calling: tuple[str, ...]


def decide(
    calling: list[str],
    min_valves: int,
    boiler_is_on: bool,
    seconds_since_change: float | None,
    min_on: float,
    min_off: float,
    demand: bool | None = None,
    force_on: bool = False,
    manual_override: bool | None = None,
) -> Decision:
    """Decide the boiler relay state, honouring minimum on/off times.

    seconds_since_change is None when the relay has not changed state yet
    (no lockout applies). `demand` overrides the valve-count rule. `force_on`
    (low-temperature safety) bypasses the minimum off time.
    """
    if demand is None:
        demand = len(calling) >= min_valves
    demand = demand or force_on
    target = demand if manual_override is None else manual_override
    if (
        manual_override is None
        and target != boiler_is_on
        and seconds_since_change is not None
        and not (force_on and target)
    ):
        lockout = min_on if boiler_is_on else min_off
        if seconds_since_change < lockout:
            target = boiler_is_on
    return Decision(demand=demand, boiler_on=target, calling=tuple(sorted(calling)))


@dataclass(frozen=True)
class RoomState:
    """Aggregated view of the valves heating one room."""

    available: bool
    active: bool
    calling: bool
    temp: float | None
    target: float | None
    pid_demand: float | None = None


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def aggregate_room(
    valves: list[ValveState],
    hysteresis: float,
    currently_calling: bool,
    sensor_temp: float | None = None,
) -> RoomState:
    """Combine all valves of a room into one state.

    - available: at least one valve responds; active: at least one is not off.
    - temp: the external room sensor if given, else the median of the valves
      (a valve sits on the radiator and reads warm, the median limits one outlier).
    - target: the highest setpoint among active valves.
    - calling: any active valve wants heat; valves without an hvac_action use
      the room temperature for the hysteresis fallback.
    """
    live = [v for v in valves if v.available]
    active = [v for v in live if v.hvac_mode not in (None, "off")]
    if not live:
        return RoomState(False, False, False, None, None)
    if not active:
        return RoomState(True, False, False, None, None)

    temps = [v.current_temp for v in active if _finite(v.current_temp)]
    temp = sensor_temp if _finite(sensor_temp) else (_median(temps) if temps else None)
    targets = [v.target_temp for v in active if _finite(v.target_temp)]
    target = max(targets) if targets else None
    pid_values = [v.pid_demand for v in active if v.pid_demand is not None]
    pid_demand = max(pid_values) if pid_values else None

    calling = False
    for v in active:
        if v.hvac_action is None and temp is not None:
            v = ValveState(v.entity_id, v.available, v.hvac_mode, None, temp, v.target_temp)
        if valve_calls_for_heat(v, hysteresis, currently_calling):
            calling = True
            break
    return RoomState(True, True, calling, temp, target, pid_demand)


@dataclass(frozen=True)
class RoomConfig:
    name: str
    valves: tuple[str, ...]
    sensor: str | None = None


def build_rooms(valves: list[str], rooms: list[dict] | None) -> list[RoomConfig]:
    """Configured rooms first; each valve not assigned to a room becomes its own room.

    A valve belongs to at most one room, and rooms only keep configured valves.
    """
    result: list[RoomConfig] = []
    used: set[str] = set()
    names: set[str] = set()
    for room in rooms or []:
        members = tuple(e for e in room.get("valves", []) if e in valves and e not in used)
        name = (room.get("name") or "").strip()
        if not members or not name or name in names:
            continue
        used.update(members)
        names.add(name)
        result.append(RoomConfig(name, members, room.get("temp_sensor") or None))
    for entity_id in valves:
        if entity_id not in used and entity_id not in names:
            result.append(RoomConfig(entity_id, (entity_id,)))
    return result
