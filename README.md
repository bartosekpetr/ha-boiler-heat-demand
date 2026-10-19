# Boiler Heat Demand

Home Assistant custom integration (HACS) that switches a **gas boiler relay** based on **heat demand from thermostatic radiator valves** (any `climate` entities).

> Unofficial, not affiliated with any boiler or valve vendor. The relay only requests heat; keep the boiler's own safety controls in place.

## How it works

- A valve calls for heat when its `hvac_action` is `heating`. If a valve doesn't report an action, it falls back to `current_temperature` vs `temperature` with hysteresis.
- Valves that are `off`, `unavailable` or `unknown` never call for heat.
- The relay turns **on** when at least *N* valves call for heat and **off** when demand disappears.
- **Minimum on / off times** protect the boiler from short-cycling.
- If the relay is unavailable, nothing is switched.

Entities: `binary_sensor` *Heat demand* (with `calling_valves` attribute) and `sensor` *Valves calling for heat*.

## Install

HACS → Custom repositories → add this repo (Integration) → install → restart → Add integration **Boiler Heat Demand**.

## Options

| Option | Default |
|---|---|
| Valves required to start | 1 |
| Minimum on time | 5 min |
| Minimum off time | 5 min |
| Hysteresis (fallback only) | 0.3 °C |

## Development

```
py -3 -m pip install pytest
py -3 -m pytest -q tests
```

Decision logic lives in `demand.py` (no Home Assistant imports) and is unit-tested. Config flow, controller and entities need testing in a real HA.

## Ideas / roadmap

- Fail-safe timeout when valves stop reporting
- Frost protection / manual override
- Per-valve weighting, pump overrun, DHW priority

MIT licensed.
