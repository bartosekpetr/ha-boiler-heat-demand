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
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DEMAND_MODE,
    CONF_HYSTERESIS,
    CONF_LEARNING,
    CONF_MIN_OFF,
    CONF_MIN_ON,
    CONF_MIN_VALVES,
    CONF_NOTIFY,
    CONF_OUTDOOR,
    CONF_PID_ATTRIBUTE,
    CONF_PID_START,
    CONF_PID_STOP,
    CONF_RELAY,
    CONF_RELAY_TIMEOUT,
    CONF_ROOMS,
    CONF_SAFETY_MIN_TEMP,
    CONF_START_DEFICIT,
    CONF_STOP_DEFICIT,
    CONF_VALVE_FAILSAFE,
    CONF_VALVES,
    CONF_VALVE_TIMEOUT,
    DEFAULT_DEMAND_MODE,
    DEFAULT_HYSTERESIS,
    DEFAULT_LEARNING,
    DEFAULT_MIN_OFF,
    DEFAULT_MIN_ON,
    DEFAULT_MIN_VALVES,
    DEFAULT_RELAY_TIMEOUT,
    DEFAULT_SAFETY_MIN_TEMP,
    DEFAULT_START_DEFICIT,
    DEFAULT_STOP_DEFICIT,
    DEFAULT_PID_START,
    DEFAULT_PID_STOP,
    DEFAULT_VALVE_FAILSAFE,
    DEFAULT_VALVE_TIMEOUT,
    DOMAIN,
    RELAY_VERIFY_SECONDS,
    SAVE_DELAY_S,
    STORAGE_VERSION,
)
from .demand import (
    FAILSAFE_HEAT,
    FAILSAFE_HOLD,
    MODE_DEFICIT,
    Decision,
    RoomConfig,
    ValveState,
    aggregate_room,
    build_rooms,
    decide,
    demand_met,
    valve_report_is_stale,
)
from .learning import RoomLearner, RoomModel, learned_call

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
        self.effective_deficit: float | None = None
        self.demand_mode = DEFAULT_DEMAND_MODE
        self.start_deficit = DEFAULT_START_DEFICIT
        self.stop_deficit = DEFAULT_STOP_DEFICIT
        self.manual_override: bool | None = None
        self.max_pid_demand: float | None = None
        self.cumulative_temp_delta: float | None = None
        self.cumulative_pid_demand: float | None = None
        self.safety_override = False
        self.learners: dict[str, RoomLearner] = {}
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.learning")
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        for entity_id, model in data.get("rooms", {}).items():
            self.learners[entity_id] = RoomLearner(model=RoomModel.from_dict(model))

    def _learner(self, entity_id: str) -> RoomLearner:
        return self.learners.setdefault(entity_id, RoomLearner())

    def _schedule_save(self) -> None:
        self._store.async_delay_save(self._dump, SAVE_DELAY_S)

    def _dump(self) -> dict:
        return {"rooms": {k: v.model.to_dict() for k, v in self.learners.items()}}

    async def async_reset_learning(self) -> None:
        self.learners.clear()
        await self._store.async_remove()
        self._publish(self.decision)

    async def async_set_manual_override(self, state: bool) -> None:
        self.manual_override = state
        await self.async_evaluate()

    async def async_resume_automatic(self) -> None:
        self.manual_override = None
        await self.async_evaluate()

    def _rooms(self, cfg: dict) -> list[RoomConfig]:
        return build_rooms(list(cfg[CONF_VALVES]), cfg.get(CONF_ROOMS))

    def _sensor_temp(self, entity_id: str | None) -> float | None:
        state = self.hass.states.get(entity_id) if entity_id else None
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        return _float(state.state)

    def _outdoor_temp(self, cfg: dict) -> float | None:
        entity_id = cfg.get(CONF_OUTDOOR)
        state = self.hass.states.get(entity_id) if entity_id else None
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        return _float(state.state)

    @property
    def _cfg(self) -> dict:
        return {**self.entry.data, **self.entry.options}

    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb)

    def start(self) -> None:
        cfg = self._cfg
        entities = [*cfg[CONF_VALVES], cfg[CONF_RELAY]]
        entities += [r.sensor for r in self._rooms(cfg) if r.sensor]
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

    def _snapshot(
        self, entity_id: str, now, timeout_seconds: float, pid_attribute: str | None
    ) -> ValveState:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return ValveState(entity_id, False, None, None, None, None)
        last_reported = getattr(state, "last_reported", None) or state.last_updated
        if valve_report_is_stale(last_reported, now, timeout_seconds):
            return ValveState(entity_id, False, None, None, None, None)
        attrs = state.attributes
        raw_pid_demand = attrs.get(pid_attribute) if pid_attribute else None
        pid_demand = (
            None if isinstance(raw_pid_demand, bool) else _float(raw_pid_demand)
        )
        if pid_demand is not None and not 0 <= pid_demand <= 100:
            pid_demand = None
        return ValveState(
            entity_id,
            True,
            state.state,
            attrs.get("hvac_action"),
            _float(attrs.get("current_temperature")),
            _float(attrs.get("temperature")),
            pid_demand,
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
        start_deficit = float(cfg.get(CONF_START_DEFICIT, DEFAULT_START_DEFICIT))
        stop_deficit = float(cfg.get(CONF_STOP_DEFICIT, DEFAULT_STOP_DEFICIT))
        self.demand_mode = mode
        self.start_deficit = start_deficit
        self.stop_deficit = stop_deficit
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
        positive_deficits: list[float] = []
        effective: list[float] = []
        pid_demands: list[float] = []
        too_cold = False
        learning_on = bool(cfg.get(CONF_LEARNING, DEFAULT_LEARNING))
        outdoor = self._outdoor_temp(cfg)
        pid_attribute = (cfg.get(CONF_PID_ATTRIBUTE) or "").strip() or None
        pid_start = float(cfg.get(CONF_PID_START, DEFAULT_PID_START))
        pid_stop = float(cfg.get(CONF_PID_STOP, DEFAULT_PID_STOP))
        mono = time.monotonic()
        for room_cfg in self._rooms(cfg):
            name = room_cfg.name
            snaps = [
                self._snapshot(e, now, timeout_seconds, pid_attribute)
                for e in room_cfg.valves
            ]
            room = aggregate_room(
                snaps,
                hysteresis,
                name in previously_calling,
                self._sensor_temp(room_cfg.sensor),
            )
            if not room.available:
                # Every valve of the room is unresponsive: apply the configured failsafe.
                if failsafe == FAILSAFE_HEAT or (
                    failsafe == FAILSAFE_HOLD and name in previously_calling
                ):
                    calling.append(name)
                    failsafe_calling = True
                continue
            if not room.active:
                continue
            pid_demands.extend(
                valve.pid_demand
                for valve in snaps
                if valve.available
                and valve.hvac_mode not in (None, "off")
                and valve.pid_demand is not None
            )
            was_calling = name in previously_calling
            wants_heat = room.calling
            deficit = None
            if room.temp is not None and room.target is not None:
                deficit = room.target - room.temp
            contribution = deficit
            if learning_on and deficit is not None:
                learner = self._learner(name)
                learner.observe(
                    mono,
                    room.temp,
                    room.target,
                    boiler_is_on and room.calling,
                    outdoor,
                    start_deficit,
                )
                if mode == MODE_DEFICIT:
                    base = deficit > stop_deficit if was_calling else deficit >= start_deficit
                else:
                    base = room.calling
                wants_heat = learned_call(
                    learner.model,
                    base,
                    was_calling,
                    room.temp,
                    room.target,
                    outdoor,
                    start_deficit,
                )
                if learner.model.ready:
                    contribution = max(deficit, start_deficit) if wants_heat else 0.0
                self._schedule_save()
            if wants_heat:
                calling.append(name)
            if deficit is not None:
                deficits.append(deficit)
                positive_deficits.append(max(0.0, deficit))
                effective.append(contribution)
            if safety_temp > 0 and room.temp is not None and room.temp <= safety_temp:
                too_cold = True
        self._calling = set(calling)
        self.max_deficit = max(deficits) if deficits else None
        self.max_pid_demand = max(pid_demands) if pid_demands else None
        self.cumulative_temp_delta = sum(positive_deficits) if positive_deficits else None
        self.cumulative_pid_demand = sum(pid_demands) if pid_demands else None
        self.safety_override = too_cold
        effective_deficit = max(effective) if effective else None
        self.effective_deficit = effective_deficit

        demand = demand_met(
            mode,
            len(calling),
            effective_deficit,
            min_valves,
            start_deficit,
            stop_deficit,
            boiler_is_on,
            failsafe_calling,
            self.max_pid_demand,
            pid_start,
            pid_stop,
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
            manual_override=self.manual_override,
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
