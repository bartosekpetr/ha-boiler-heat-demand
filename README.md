# Boiler Heat Demand

Home Assistant custom integration (HACS) that switches a **gas boiler relay** based on **heat demand from thermostatic radiator valves** (any `climate` entities).

> Unofficial, not affiliated with any boiler or valve vendor. The relay only requests heat; keep the boiler's own safety controls in place.

## How it works

1. **Select valves** – any `climate` entities. A valve in `off` mode (or unavailable) never counts.
2. **Is a valve requesting heat?** – `hvac_action == heating`; if the valve has no action, `current_temperature` vs `temperature` with hysteresis is used.
3. **Demand mode** (configurable):
   - *Valve count* – start when at least *N* valves call for heat.
   - *Temperature deficit* – start when the largest `target − current` among active valves reaches **start deficit**; keep heating until it falls to **stop deficit**. The gap between the two thresholds prevents on/off flapping.
4. **Anti-short-cycling** – minimum on and off times. Recommended: min on/off 5–10 min, start deficit ≈ 0.5 °C, stop deficit ≈ 0.1 °C.
5. **Low-temperature safety** – if any active valve's room is at or below the safety temperature (default 8 °C, 0 disables), the boiler is turned on even during the minimum off time.
6. **Output** – a generic `switch` / `input_boolean` relay.

### Unresponsive valves
A valve that is `unavailable`, `unknown` or has not reported within the timeout (default 30 min, 0 disables) follows the **If a valve does not respond** setting: *ignore* (default), *assume it calls for heat*, or *keep its last known demand*.

### Unresponsive or stuck relay (critical alerts)
A critical alert is raised (Repairs issue with critical severity, persistent notification, log entry and optionally a critical push via the configured `notify.*` service) when:
- the relay is unavailable longer than the configured time (it may be stuck **on**),
- a switch command fails,
- the relay doesn't reach the commanded state within 60 s (the command is re-sent while demand persists).

Alerts clear automatically when the relay behaves again.

Entities: `binary_sensor` *Heat demand* (attributes `calling_valves`, `max_temperature_deficit`, `safety_override`, `alerts`) and `sensor` *Valves calling for heat*.

## Install

HACS → Custom repositories → add this repo (Integration) → install → restart → Add integration **Boiler Heat Demand**.

## Options

| Option | Default |
|---|---|
| Demand mode | Valve count |
| Valves required to start | 1 |
| Start / stop deficit (deficit mode) | 0.5 / 0.1 °C |
| Minimum on time | 5 min |
| Minimum off time | 5 min |
| Hysteresis (fallback only) | 0.3 °C |
| Low-temperature safety | 8 °C (0 disables) |
| Valve report timeout | 30 min (0 disables) |
| If a valve does not respond | Ignore |
| Relay unavailable alert after | 5 min |
| Critical notify service | none |

Stale valves are treated as unavailable. The timeout uses Home Assistant's last reported time, falling back to the last state-change time on older Home Assistant versions.

## Development

```
py -3 -m pip install pytest
py -3 -m pytest -q tests
```

Decision logic lives in `demand.py` (no Home Assistant imports) and is unit-tested. Config flow, controller and entities need testing in a real HA.

## Ideas / roadmap

- Frost protection / manual override
- Per-valve weighting, pump overrun, DHW priority

MIT licensed.
