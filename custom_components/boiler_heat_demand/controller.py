"""Evaluates valve demand and drives the boiler relay."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.components import persistent_notification
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DEMAND_MODE,
    CONF_HYSTERESIS,
    CONF_MIN_OFF,
    CONF_MIN_ON,
    CONF_MIN_VALVES,
    CONF_NOTIFY,
    CONF_RELAY,
    CONF_RELAY_TIMEOUT,
    CONF_SAFETY_MIN_TEMP,
    CONF_START_DEFICIT,
    CONF_STOP_DEFICIT,
    CONF_VALVE_FAILSAFE,
    CONF_VALVES,
    CONF_VALVE_TIMEOUT,
    DEFAULT_DEMAND_MODE,
    DEFAULT_HYSTERESIS,
    DEFAULT_MIN_OFF,
    DEFAULT_MIN_ON,
    DEFAULT_MIN_VALVES,
    DEFAULT_RELAY_TIMEOUT,
    DEFAULT_SAFETY_MIN_TEMP,
    DEFAULT_START_DEFICIT,
    DEFAULT_STOP_DEFICIT,
    DEFAULT_VALVE_FAILSAFE,
    DEFAULT_VALVE_TIMEOUT,
    DOMAIN,
    RELAY_VERIFY_SECONDS,
)
from .demand import (
    FAILSAFE_HEAT,
    FAILSAFE_HOLD,
    Decision,
    ValveState,
    decide,
    demand_met,
    valve_calls_for_heat,
    valve_deficit,
    valve_is_too_cold,
    valve_report_is_stale,
)

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
        self._commanded: bool | None = None
        self._commanded_at: float | None = None
        self._relay_bad_since: float | None = None
        self.alerts: set[str] = set()
        self.max_deficit: float | None = None
        self.safety_override = False
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

    def _snapshot(self, entity_id: str, now, timeout_seconds: float) -> ValveState:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return ValveState(entity_id, False, None, None, None, None)
        last_reported = getattr(state, "last_reported", None) or state.last_updated
        if valve_report_is_stale(last_reported, now, timeout_seconds):
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
        timeout_seconds = float(cfg.get(CONF_VALVE_TIMEOUT, DEFAULT_VALVE_TIMEOUT)) * 60
        failsafe = cfg.get(CONF_VALVE_FAILSAFE, DEFAULT_VALVE_FAILSAFE)
        mode = cfg.get(CONF_DEMAND_MODE, DEFAULT_DEMAND_MODE)
        safety_temp = float(cfg.get(CONF_SAFETY_MIN_TEMP, DEFAULT_SAFETY_MIN_TEMP))
        min_valves = int(cfg.get(CONF_MIN_VALVES, DEFAULT_MIN_VALVES))
        now = dt_util.utcnow()

        relay_state = self.hass.states.get(relay)
        relay_ok = relay_state is not None and relay_state.state not in (
            STATE_UNAVAILABLE,
            STATE_UNKNOWN,
        )
        boiler_is_on = relay_ok and relay_state.state == STATE_ON
        previously_calling = self._calling

        calling: list[str] = []
        failsafe_calling = False
        deficits: list[float] = []
        too_cold = False
        for entity_id in cfg[CONF_VALVES]:
            snap = self._snapshot(entity_id, now, timeout_seconds)
            if not snap.available:
                # Unresponsive valve: apply the configured failsafe.
                if failsafe == FAILSAFE_HEAT or (
                    failsafe == FAILSAFE_HOLD and entity_id in previously_calling
                ):
                    calling.append(entity_id)
                    failsafe_calling = True
                continue
            if valve_calls_for_heat(snap, hysteresis, entity_id in previously_calling):
                calling.append(entity_id)
            deficit = valve_deficit(snap)
            if deficit is not None:
                deficits.append(deficit)
            too_cold = too_cold or valve_is_too_cold(snap, safety_temp)
        self._calling = set(calling)
        self.max_deficit = max(deficits) if deficits else None
        self.safety_override = too_cold

        demand = demand_met(
            mode,
            len(calling),
            self.max_deficit,
            min_valves,
            float(cfg.get(CONF_START_DEFICIT, DEFAULT_START_DEFICIT)),
            float(cfg.get(CONF_STOP_DEFICIT, DEFAULT_STOP_DEFICIT)),
            boiler_is_on,
            failsafe_calling,
        )

        if not relay_ok:
            _LOGGER.debug("Relay %s unavailable, not switching", relay)
            await self._check_relay(cfg, None, False)
            self._publish(Decision(demand or too_cold, False, tuple(sorted(calling))))
            return
        since = None
        if self._last_change is not None:
            since = time.monotonic() - self._last_change

        decision = decide(
            calling,
            min_valves,
            boiler_is_on,
            since,
            float(cfg.get(CONF_MIN_ON, DEFAULT_MIN_ON)) * 60,
            float(cfg.get(CONF_MIN_OFF, DEFAULT_MIN_OFF)) * 60,
            demand=demand,
            force_on=too_cold,
        )
        if decision.boiler_on == boiler_is_on:
            # Relay already matches what we want (e.g. changed manually): nothing to verify.
            self._commanded = None
            self._commanded_at = None
        await self._check_relay(cfg, relay_state, boiler_is_on)
        if decision.boiler_on != boiler_is_on:
            await self._command(relay, decision.boiler_on)
        self._publish(decision)

    def _needs_retry(self, boiler_is_on: bool) -> bool:
        """True if a previous command did not take effect within the verify window."""
        return (
            self._commanded is not None
            and self._commanded != boiler_is_on
            and self._commanded_at is not None
            and time.monotonic() - self._commanded_at >= RELAY_VERIFY_SECONDS
        )

    async def _command(self, relay: str, on: bool) -> None:
        try:
            await self.hass.services.async_call(
                "switch" if relay.startswith("switch.") else "homeassistant",
                "turn_on" if on else "turn_off",
                {"entity_id": relay},
                blocking=True,
            )
        except Exception as err:  # noqa: BLE001 - any service failure must raise an alert
            _LOGGER.error("Switching relay %s failed: %s", relay, err)
            self._raise_alert(
                "relay_command_failed",
                f"Could not turn {relay} {'on' if on else 'off'}: {err}. "
                "The boiler relay may be stuck in its current state.",
            )
            self._mark_commanded(on)
            return
        if self._mark_commanded(on):
            self._last_change = time.monotonic()

    def _mark_commanded(self, on: bool) -> bool:
        """Record the command; keep the original timestamp when re-sending the same one."""
        if self._commanded == on:
            return False
        self._commanded, self._commanded_at = on, time.monotonic()
        return True

    async def _check_relay(self, cfg: dict, relay_state, boiler_is_on: bool) -> None:
        """Raise or clear critical alerts for an unresponsive or stuck relay."""
        relay = cfg[CONF_RELAY]
        timeout = float(cfg.get(CONF_RELAY_TIMEOUT, DEFAULT_RELAY_TIMEOUT)) * 60
        if relay_state is None:
            if self._relay_bad_since is None:
                self._relay_bad_since = time.monotonic()
            if time.monotonic() - self._relay_bad_since >= timeout:
                last = "on" if self._commanded else "off" if self._commanded is False else "unknown"
                self._raise_alert(
                    "relay_unavailable",
                    f"Boiler relay {relay} has been unavailable for over "
                    f"{int(timeout // 60)} min (last commanded state: {last}). "
                    "It may be stuck ON. Check the boiler manually.",
                )
        else:
            self._relay_bad_since = None
            self._clear_alert("relay_unavailable")
            if self._needs_retry(boiler_is_on):
                self._raise_alert(
                    "relay_stuck",
                    f"Boiler relay {relay} is {'on' if boiler_is_on else 'off'} but was "
                    f"commanded {'on' if self._commanded else 'off'} more than "
                    f"{RELAY_VERIFY_SECONDS}s ago. It may be stuck.",
                )
            elif self._commanded is None or self._commanded == boiler_is_on:
                self._clear_alert("relay_stuck")
                self._clear_alert("relay_command_failed")

    def _raise_alert(self, key: str, message: str) -> None:
        if key in self.alerts:
            return
        self.alerts.add(key)
        _LOGGER.critical(message)
        title = "Boiler relay problem"
        notification_id = f"{DOMAIN}_{self.entry.entry_id}_{key}"
        persistent_notification.async_create(
            self.hass, message, title=title, notification_id=notification_id
        )
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"{self.entry.entry_id}_{key}",
            is_fixable=False,
            severity=ir.IssueSeverity.CRITICAL,
            translation_key=key,
            translation_placeholders={"relay": self._cfg[CONF_RELAY]},
        )
        service = (self._cfg.get(CONF_NOTIFY) or "").strip()
        if service:
            self.hass.async_create_task(self._send_notify(service, title, message))

    async def _send_notify(self, service: str, title: str, message: str) -> None:
        name = service.removeprefix("notify.")
        try:
            await self.hass.services.async_call(
                "notify",
                name,
                {
                    "title": title,
                    "message": message,
                    "data": {
                        "push": {"sound": {"name": "default", "critical": 1, "volume": 1.0}},
                        "ttl": 0,
                        "priority": "high",
                    },
                },
                blocking=True,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Critical notification via %s failed: %s", service, err)

    def _clear_alert(self, key: str) -> None:
        if key not in self.alerts:
            return
        self.alerts.discard(key)
        persistent_notification.async_dismiss(
            self.hass, f"{DOMAIN}_{self.entry.entry_id}_{key}"
        )
        ir.async_delete_issue(self.hass, DOMAIN, f"{self.entry.entry_id}_{key}")

    def _publish(self, decision: Decision) -> None:
        self.decision = decision
        for cb in list(self._listeners):
            cb()
