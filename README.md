# Boiler Heat Demand

Home Assistant custom integration (HACS) that switches a **gas boiler relay** based on **heat demand from thermostatic radiator valves** (any `climate` entities).

> Unofficial, not affiliated with any boiler or valve vendor. The relay only requests heat; keep the boiler's own safety controls in place.

## How it works

1. **Select valves and group them into rooms** â€“ any `climate` entities. Valves in the same room are grouped in the setup (optionally with a room temperature sensor); ungrouped valves are each their own room. Everything below works per **room**.
2. **Room state** â€“ temperature is the room sensor if set, otherwise the median of its valves (one radiator-warmed valve can't skew it). The room target is the highest setpoint among its active valves. A room whose valves are all `off` never counts; if only some valves fail, the room keeps working from the others.
3. **Is a room requesting heat?** â€“ any of its valves has `hvac_action == heating`; valves without an action use the room temperature vs target with hysteresis.
4. **Demand mode** (configurable):
   - *Valve count* â€“ start when at least *N* rooms call for heat.
   - *Temperature deficit* â€“ start when the largest room `target â’ current` reaches **start deficit**; keep heating until it falls to **stop deficit**. The gap between the two thresholds prevents on/off flapping.
5. **Anti-short-cycling** â€“ minimum on and off times. Recommended: min on/off 5â€“10 min, start deficit â‰ 0.5 Â°C, stop deficit â‰ 0.1 Â°C.
6. **Low-temperature safety** â€“ if any active room is at or below the safety temperature (default 8 Â°C, 0 disables), the boiler is turned on even during the minimum off time.
7. **Output** â€“ a generic `switch` / `input_boolean` relay.

### Unresponsive valves
A valve that is `unavailable`, `unknown` or has not reported within the timeout (default 30 min, 0 disables) is ignored while other valves in its room respond. When **all** valves of a room are unresponsive, the room follows the **If a valve does not respond** setting: *ignore* (default), *assume it calls for heat*, or *keep its last known demand*.

### Unresponsive or stuck relay (critical alerts)
A critical alert is raised (Repairs issue with critical severity, persistent notification, log entry and optionally a critical push via the configured `notify.*` service) when:
- the relay is unavailable longer than the configured time (it may be stuck **on**),
- a switch command fails,
- the relay doesn't reach the commanded state within 60 s (the command is re-sent while demand persists).

Alerts clear automatically when the relay behaves again.

Entities: `binary_sensor` *Heat demand* (attributes `calling_rooms`, `max_temperature_deficit`, `safety_override`, `alerts`), `sensor` *Rooms calling for heat*, diagnostic `sensor` *Rooms learned* (per-room model as attributes), diagnostic `sensor` *Maximum room temperature deficit* (raw `target - current`, plus the learning-adjusted deficit and configured thresholds), and buttons for *Boiler on*, *Boiler off*, *Resume automatic control* and *Reset learning*.

Manual boiler buttons hold the selected state until *Resume automatic control* is pressed. Manual control bypasses the minimum on/off timers; manual off also takes precedence over the low-temperature safety override. The selection is not persisted, so the integration returns to automatic control after a Home Assistant restart.

### Self-learning
Each room is modelled separately from its room temperature (sensor or valve median), no extra hardware needed:
- **Heating rate** (Â°C/h with the boiler on), **cooling rate** (boiler off; per Â°C above outdoor if an outdoor sensor is set), **lag** (minutes until the room starts rising) and **coast rise** (how far it keeps rising after heating stops, e.g. warm radiators).
- **Early stop:** heating stops when `current + coast rise â‰Ą target`, which reduces overshoot.
- **Pre-start:** heating starts when the temperature predicted after the lag would fall below `target â’ start threshold`.
- **Self-tuning:** after each cycle the start threshold and stop point are nudged by 0.1 Â°C if the room overshot or undershot. Values are clamped, and the start threshold always stays above the stop point to prevent flapping.
- A room is used only after **3 complete heating cycles**; before that the fixed rules apply. Minimum on/off times and the low-temperature safety always take precedence.
- Models are stored across restarts. Use *Reset learning* after big changes (new radiator, insulation). Learning can be disabled in the options. It only learns from the room's own readings, so rooms with coarse sensors (0.5 Â°C steps) learn more slowly.

## Install

HACS â†’ Custom repositories â†’ add this repo (Integration) â†’ install â†’ restart â†’ Add integration **Boiler Heat Demand**.

## Options

| Option | Default |
|---|---|
| Demand mode | Valve count |
| Rooms required to start | 1 |
| Start / stop deficit (deficit mode) | 0.5 / 0.1 Â°C |
| Minimum on time | 5 min |
| Minimum off time | 5 min |
| Hysteresis (fallback only) | 0.3 Â°C |
| Low-temperature safety | 8 Â°C (0 disables) |
| Valve report timeout | 30 min (0 disables) |
| If a valve does not respond | Ignore |
| Relay unavailable alert after | 5 min |
| Critical notify service | none |
| Self-learning | On |
| Outdoor temperature sensor | none |

Stale valves are treated as unavailable. The timeout uses Home Assistant's last reported time, falling back to the last state-change time on older Home Assistant versions.

## Development

```
py -3 -m pip install pytest
py -3 -m pytest -q tests
```

Decision logic lives in `demand.py` (no Home Assistant imports) and is unit-tested. Config flow, controller and entities need testing in a real HA.

## Ideas / roadmap

- Frost protection
- Per-valve weighting, pump overrun, DHW priority

MIT licensed.
