# Agent guide

## Project

`boiler_heat_demand` is a Home Assistant custom integration (HACS, MIT) that switches a gas-boiler relay from thermostatic radiator valve (`climate`) heat demand. The integration requests heat through a generic `switch` or `input_boolean`; it does not replace boiler safety controls. Repository: `bartosekpetr/ha-boiler-heat-demand`.

Inspect `git status` before editing. Preserve existing worktree changes and do not revert unrelated edits.

## Architecture

- `custom_components/boiler_heat_demand/demand.py` contains pure, Home-Assistant-independent demand and room logic. Keep it unit-testable.
- `controller.py` reads Home Assistant states, aggregates rooms, applies demand/failsafe/safety/learning rules, drives and checks the relay, and publishes updates to entities.
- `learning.py` contains the persisted per-room thermal learner.
- `config_flow.py` defines setup/options and room grouping.
- `binary_sensor.py`, `sensor.py`, and `button.py` define platform entities.
- `__init__.py` sets up and unloads the controller. `device_info(entry)` groups every entity for a config entry under one device named **Automated Boiler**.
- `const.py` holds configuration keys, defaults, and platform names.

## Current behavior and entity contract

- Valves are grouped into configured rooms; ungrouped valves each form a room. A configured room uses its temperature sensor when available, otherwise the median active-valve temperature, and the highest active-valve target.
- Demand modes are valve/room count, largest temperature deficit, and PID demand. PID mode reads one configurable climate attribute from each valve; numeric values in `[0, 100]` are valid. The boiler starts/stops using configurable PID thresholds (defaults 20% / 5%). The maximum valid active-valve value is the demand signal. If no active valve has a valid PID value, PID mode falls back to valve-count demand.
- Existing minimum on/off lockouts, low-temperature safety override, valve timeout/failsafes, relay alerts, and optional room self-learning remain in effect.
- Manual `Boiler on`, `Boiler off`, and `Resume automatic control` buttons are available. Manual control bypasses min on/off timers; manual off takes precedence over low-temperature safety. The override resets to automatic after HA restart.
- `Maximum PID demand` is the pre-existing maximum-value sensor; keep its entity identity and behavior intact when adding aggregate sensors.
- `Cumulative PID demand` is a live sum of valid PID values across active valves. It can exceed 100%; it is not a time-integrated total.
- `Cumulative temperature delta` is a live sum of `max(0, target - current)` across active rooms with readable temperature and target. Rooms at/above target contribute zero; it is not a time-integrated total.
- Other entities include `Heat demand` (attributes include calling rooms, max temperature deficit, safety override, and alerts), `Rooms calling for heat`, diagnostic `Rooms learned`, diagnostic `Maximum room temperature deficit`, and the four buttons above.
- Keep entity unique IDs stable. Keep `strings.json` and `translations/en.json` identical.

## Tests and validation

- Pure-logic tests: `tests/test_demand.py` and `tests/test_learning.py`.
- Home Assistant glue tests: `tests/test_ha_glue.py` cover PID parsing/relay behavior, aggregate sensor values, and shared device association. They use `pytest-homeassistant-custom-component` and run on Linux; the module skips on Windows because Home Assistant's test harness is unsupported there.
- Windows/local validation:
  - `py -3 -m pytest -q tests`
  - `py -3 -m compileall -q custom_components tests`
- CI is `.github/workflows/validate.yml`: Python tests and compileall, plus hassfest and HACS validation. The HA test dependency is installed in CI; do not add it to integration runtime requirements.
- Update the README for user-visible behavior changes. `README.md` is the user/developer documentation.
- Before claiming validation, report whether HA-specific tests actually ran or were skipped.

## Change and release conventions

- Prefer focused changes following existing Home Assistant entity/config-flow patterns. Preserve safety overrides and relay handling when changing demand logic.
- Do not add runtime dependencies unless required; runtime dependencies are listed in `custom_components/boiler_heat_demand/manifest.json`.
- Do not change the integration version or commit unless the user requests it.
- When committing, use author `bartosekpetr` and include this final trailer:
  `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`

## Roadmap

README-listed ideas not yet implemented include frost protection, per-valve weighting, pump overrun, and DHW priority. Config flow and other HA glue may need broader integration-test coverage. Confirm scope with the user before starting a roadmap item.
