"""Pure heat-demand logic. No Home Assistant imports so it stays unit-testable."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


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
    if valve.current_temp is None or valve.target_temp is None:
        return False
    if currently_calling:
        return valve.current_temp < valve.target_temp
    return valve.current_temp <= valve.target_temp - hysteresis


MODE_COUNT = "valve_count"
MODE_DEFICIT = "temperature_deficit"

FAILSAFE_IGNORE = "ignore"
FAILSAFE_HEAT = "call_for_heat"
FAILSAFE_HOLD = "hold_last"


def valve_deficit(valve: ValveState) -> float | None:
    """Degrees below target for a valve that is available and not off, else None."""
    if not valve.available or valve.hvac_mode in (None, "off"):
        return None
    if valve.current_temp is None or valve.target_temp is None:
        return None
    return valve.target_temp - valve.current_temp


def valve_is_too_cold(valve: ValveState, safety_min_temp: float) -> bool:
    """True when an active valve's room is at or below the safety temperature (0 disables)."""
    if safety_min_temp <= 0 or not valve.available or valve.hvac_mode in (None, "off"):
        return False
    return valve.current_temp is not None and valve.current_temp <= safety_min_temp


def demand_met(
    mode: str,
    calling_count: int,
    max_deficit: float | None,
    min_valves: int,
    start_deficit: float,
    stop_deficit: float,
    boiler_is_on: bool,
    failsafe_calling: bool = False,
) -> bool:
    """Evaluate demand by valve count or by the largest temperature deficit.

    Deficit mode uses separate start/stop thresholds (start >= stop) so the
    boiler does not toggle around a single value.
    """
    if mode == MODE_DEFICIT:
        if failsafe_calling:
            return True
        if max_deficit is None:
            return False
        if boiler_is_on:
            return max_deficit > stop_deficit
        return max_deficit >= start_deficit
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
) -> Decision:
    """Decide the boiler relay state, honouring minimum on/off times.

    seconds_since_change is None when the relay has not changed state yet
    (no lockout applies). `demand` overrides the valve-count rule. `force_on`
    (low-temperature safety) bypasses the minimum off time.
    """
    if demand is None:
        demand = len(calling) >= min_valves
    demand = demand or force_on
    target = demand
    if target != boiler_is_on and seconds_since_change is not None and not (force_on and target):
        lockout = min_on if boiler_is_on else min_off
        if seconds_since_change < lockout:
            target = boiler_is_on
    return Decision(demand=demand, boiler_on=target, calling=tuple(sorted(calling)))
