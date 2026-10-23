# Boiler Heat Demand

Home Assistant custom integration (HACS) that switches a **gas boiler relay** based on **heat demand from thermostatic radiator valves** (any `climate` entities).

> Unofficial, not affiliated with any boiler or valve vendor. The relay only requests heat; keep the boiler's own safety controls in place.

## How it works

1. **Select valve devices; rooms are detected for you** â€“ pick the thermostatic valve devices; the `climate` entity of each device is used (climate entities without a device can be added separately). Rooms come from the **areas** your valves already have in Home Assistant (the entity's own area, otherwise its device's area). Setup shows the detected rooms and you only confirm them; you are asked to assign a room only for valves that have no area (or you can decline the detection and group valves by hand, optionally with a room temperature sensor). Valves left unassigned are each their own room. Everything below works per **room**.
2. **Room state** â€“ temperature is the room sensor if set, otherwise the median of its valves (one radiator-warmed valve can't skew it). The room target is the highest setpoint among its active valves. A room whose valves are all `off` never counts; if only some valves fail, the room keeps working from the others.
3. **Is a room requesting heat?** â€“ any of its valves has `hvac_action == heating`; valves without an action use the room temperature vs target with hysteresis.
4. **Demand mode** (configurable):
   - *PID heating demand* - start when the highest active valve PID demand reaches the configured start percentage; keep heating until it falls to the stop percentage. The configured climate attribute must report a numeric value from 0 to 100. If no active valve provides a valid value, the integration falls back to valve-count demand.
   - *Valve count* â€“ start when at least *N* rooms call for heat.
   - *Temperature deficit* â€“ start when the largest room `target â’ current` reaches **start deficit**; keep heating until it falls to **stop deficit**. The gap between the two thresholds prevents on/off flapping.
5. **Anti-short-cycling** â€“ minimum on and off times. Recommended: min on/off 5â€“10 min, start deficit â‰ 0.5 Â°C, stop deficit â‰ 0.1 Â°C.
6. **Low-temperature safety** â€“ if any active room is at or below the safety temperature (default 8 Â°C, 0 disables), the boiler is turned on even during the minimum off time. The room temperature comes from the room sensor when it is valid and fresh, otherwise from the valves. A room whose valves are all unresponsive is still protected when it has a valid room sensor. Rooms whose valves are switched `off` are not heated, so they do not trigger the safety.
7. **Output** â€“ a generic `switch` / `input_boolean` relay.

### Unresponsive valves
A valve that is `unavailable`, `unknown` or has not reported within the timeout (default 30 min, 0 disables) is ignored while other valves in its room respond. When **all** valves of a room are unresponsive, the room follows the **If a valve does not respond** setting: *ignore* (default), *assume it calls for heat*, or *keep its last known demand*.

### Unresponsive or stuck relay (critical alerts)
A critical alert is raised (Repairs issue with critical severity, persistent notification, log entry and optionally a critical push via the configured `notify.*` service) when:
- the relay is unavailable longer than the configured time (it may be stuck **on**),
- a switch command fails,
- the relay doesn't reach the commanded state within 60 s (the command is re-sent while demand persists).

Alerts clear automatically when the relay behaves again.

Entities: `binary_sensor` *Heat demand* (attributes `calling_rooms`, `max_temperature_deficit`, `safety_override`, `alerts`), `sensor` *Rooms calling for heat*, diagnostic `sensor` *Rooms learned* (per-room model as attributes), diagnostic `sensor` *Maximum room temperature deficit* (raw `target - current`, plus the learning-adjusted deficit and configured thresholds), `sensor` *Maximum PID demand* (highest valid PID value reported by an active valve), `sensor` *Cumulative PID demand* (sum across active valves; can exceed 100%), `sensor` *Cumulative temperature delta* (sum of positive target-minus-current deltas across active rooms), and buttons for *Boiler on*, *Boiler off*, *Resume automatic control* and *Reset learning*. All entities are grouped under one device called **Automated Boiler**.

Manual boiler buttons hold the selected state until *Resume automatic control* is pressed or the **manual override timeout** elapses (default 120 minutes, configurable, 0 = never); the remaining time is shown in the `manual_override_seconds_left` attribute of the *Heat demand* sensor. Manual control bypasses the minimum on/off timers; manual off also takes precedence over the low-temperature safety override while it is active. The selection is not persisted, so the integration returns to automatic control after a Home Assistant restart.

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
| PID demand source | Detected automatically per valve device |
| PID start / stop demand (PID mode) | 20 / 5 % |
| Rooms required to start | 1 |
| Start / stop deficit (deficit mode) | 0.5 / 0.1 Â°C |
| Minimum on time | 5 min |
| Minimum off time | 5 min |
| Hysteresis (fallback only) | 0.3 Â°C |
| Low-temperature safety | 8 Â°C (0 disables) |
| Valve report timeout | 30 min (0 disables) |
| If a valve does not respond | Ignore |
| Manual boiler on/off expires after | 120 min (0 = never) |
| Relay unavailable alert after | 5 min |
| Critical notify service | none |
| Self-learning | On |
| Outdoor temperature sensor | none |

Stale valves are treated as unavailable. The timeout uses Home Assistant's last reported time, falling back to the last state-change time on older Home Assistant versions. External room sensors are checked the same way but with a longer window (at least 2 hours, because battery sensors report rarely); a stale sensor is ignored and the valves are used instead. Setting the timeout to 0 disables both checks.

## Security and safety notes

- **Input validation:** temperatures from valves and sensors must be finite numbers between -50 and 60 °C (°F and K sensors are converted, other units rejected). `nan`, `inf` and out-of-range values are ignored, so a faulty sensor falls back to the valves instead of disabling frost protection. Stored learning data is validated and clamped when loaded.
- **Failures are loud:** if the control logic itself fails, a critical *Boiler control stopped* alert is raised (Repairs issue, notification and the optional notify service). The relay keeps its last state until the problem is fixed, so check the alert.
- **Removing the integration** turns the relay off if it is on, because nothing manages it afterwards. Reloading after an options change does not touch the relay.
- **Manual buttons are ordinary Home Assistant entities.** Anyone who can press buttons (dashboards, voice assistants, automations) can override the boiler, but the override now expires. Do not expose the *Boiler on/off* buttons to voice assistants or untrusted users.
- **Always keep the boiler's own safety controls.** This integration only requests heat.
- CI actions are pinned to commit SHAs and the test dependency is version-pinned; Dependabot keeps them updated. See [SECURITY.md](SECURITY.md) for reporting vulnerabilities.

For PID mode, nothing needs to be configured. In setup you pick the valve **devices** (for example *Chodba vstup*); the integration takes the `climate` entity from each device and finds the device's **PI heating demand** sensor (for example `sensor.chodba_vstup_pi_heating_demand`) on its own. The sensor is recognised by its name, translation key or unique id, so renamed entity IDs keep working; it must be a sensor reporting a percentage from 0 to 100. If a device has no such sensor, the integration falls back to a demand attribute on the climate entity (known names such as `pi_heating_demand`, `pid_demand`, `pi_output`, `heating_demand`, `valve_opening_degree` and `valve_position`, then other names that look like a demand or valve-opening value; targets, offsets, limits and PID gains are ignored). Valves can be mixed freely, and the *Maximum PID demand* sensor lists the source used for each valve (`pid_source_by_valve`, either a sensor entity or an attribute name). Valves without any PID source are simply skipped. The integration combines active valves by taking the highest value, so one room with a strong heat request can start the boiler. When no active valve provides a valid value, ordinary valve-count logic is used as a fallback. Minimum on/off times and low-temperature safety still apply.

**Rooms and areas:** room names are the Home Assistant area names. Changing the area of a valve later does not change an existing setup; open the integration options and enable *Re-detect rooms from Home Assistant areas* to confirm the rooms again (rooms are learned per room name, so a renamed room starts learning again). Existing installations keep their current rooms until you do this.

**Upgrading:** existing installations keep working without changes. They stored climate entity IDs, and the PI heating demand sensor is looked up from each climate entity's device automatically. A manual attribute name set in an earlier beta is still honoured first. When you open the options, devices are pre-selected from your current valves; climate entities that do not belong to a device stay in the optional *Other valve climate entities* field.

The cumulative sensors are live sums, not running totals over time. Cumulative PID demand sums every valid active-valve PID value (so it may exceed 100%). Cumulative temperature delta sums `max(0, target - current)` for each active room with readable temperatures; rooms at or above target contribute zero. The Maximum PID demand sensor reports the single highest active-valve value and remains separate from the cumulative sensor.

## Development

```
py -3 -m pip install pytest
py -3 -m pytest -q tests
py -3 -m compileall -q custom_components tests
```

Decision logic lives in `demand.py` (no Home Assistant imports) and is unit-tested. HA-level tests cover controller PID parsing and relay behavior, aggregate sensors, and entity device grouping; they run on Linux in CI because Home Assistant's test harness is not supported on Windows. GitHub Actions also runs hassfest and HACS validation.

## Ideas / roadmap

- Frost protection
- Per-valve weighting, pump overrun, DHW priority

MIT licensed.
