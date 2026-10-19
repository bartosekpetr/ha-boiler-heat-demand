"""Evaluates valve demand and drives the boiler relay."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval

from .const import (
    CONF_HYSTERESIS,
    CONF_MIN_OFF,
    CONF_MIN_ON,
    CONF_MIN_VALVES,
    CONF_RELAY,
    CONF_VALVES,
    DEFAULT_HYSTERESIS,
    DEFAULT_MIN_OFF,
    DEFAULT_MIN_ON,
    DEFAULT_MIN_VALVES,
)
from .demand import Decision, ValveState, decide, valve_calls_for_heat

_LOGGER = logging.getLogger(__name__)


def _float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class BoilerController:
    """Listens to valve states and switches the relay."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.decision = Decision(False, False, ())
        self._calling: set[str] = set()
        self._last_change: float | None = None
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []

    @property
    def _cfg(self) -> dict:
        return {**self.entry.data, **self.entry.options}

    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb)

    def start(self) -> None:
        cfg = self._cfg
        entities = [*cfg[CONF_VALVES], cfg[CONF_RELAY]]
        self._unsubs.append(async_track_state_change_event(self.hass, entities, self._on_change))
        # Re-evaluate periodically so min on/off lockouts expire without a state change.
        self._unsubs.append(
            async_track_time_interval(self.hass, self._on_timer, timedelta(seconds=30))
        )
        self.hass.async_create_task(self.async_evaluate())

    def stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    @callback
    def _on_change(self, event: Event) -> None:
        self.hass.async_create_task(self.async_evaluate())

    async def _on_timer(self, _now) -> None:
        await self.async_evaluate()

    def _snapshot(self, entity_id: str) -> ValveState:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return ValveState(entity_id, False, None, None, None, None)
        attrs = state.attributes
        return ValveState(
            entity_id,
            True,
            state.state,
            attrs.get("hvac_action"),
            _float(attrs.get("current_temperature")),
            _float(attrs.get("temperature")),
        )

    async def async_evaluate(self) -> None:
        cfg = self._cfg
        relay = cfg[CONF_RELAY]
        hysteresis = float(cfg.get(CONF_HYSTERESIS, DEFAULT_HYSTERESIS))

        calling = []
        for entity_id in cfg[CONF_VALVES]:
            if valve_calls_for_heat(self._snapshot(entity_id), hysteresis, entity_id in self._calling):
                calling.append(entity_id)
        self._calling = set(calling)

        relay_state = self.hass.states.get(relay)
        if relay_state is None or relay_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            _LOGGER.debug("Relay %s unavailable, not switching", relay)
            min_valves = int(cfg.get(CONF_MIN_VALVES, DEFAULT_MIN_VALVES))
            self._publish(Decision(len(calling) >= min_valves, False, tuple(sorted(calling))))
            return
        boiler_is_on = relay_state.state == STATE_ON
        since = None
        if self._last_change is not None:
            since = time.monotonic() - self._last_change

        decision = decide(
            calling,
            int(cfg.get(CONF_MIN_VALVES, DEFAULT_MIN_VALVES)),
            boiler_is_on,
            since,
            float(cfg.get(CONF_MIN_ON, DEFAULT_MIN_ON)) * 60,
            float(cfg.get(CONF_MIN_OFF, DEFAULT_MIN_OFF)) * 60,
        )
        if decision.boiler_on != boiler_is_on:
            await self.hass.services.async_call(
                "switch" if relay.startswith("switch.") else "homeassistant",
                "turn_on" if decision.boiler_on else "turn_off",
                {"entity_id": relay},
                blocking=True,
            )
            self._last_change = time.monotonic()
        self._publish(decision)

    def _publish(self, decision: Decision) -> None:
        self.decision = decision
        for cb in list(self._listeners):
            cb()
