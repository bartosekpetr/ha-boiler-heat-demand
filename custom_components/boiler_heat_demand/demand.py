"""Pure heat-demand logic. No Home Assistant imports so it stays unit-testable."""
from __future__ import annotations

from dataclasses import dataclass


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
) -> Decision:
    """Decide the boiler relay state, honouring minimum on/off times.

    seconds_since_change is None when the relay has not changed state yet
    (no lockout applies).
    """
    demand = len(calling) >= min_valves
    target = demand
    if target != boiler_is_on and seconds_since_change is not None:
        lockout = min_on if boiler_is_on else min_off
        if seconds_since_change < lockout:
            target = boiler_is_on
    return Decision(demand=demand, boiler_on=target, calling=tuple(sorted(calling)))
