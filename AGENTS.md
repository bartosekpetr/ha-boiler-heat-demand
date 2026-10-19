# AGENTS.md

Home Assistant custom integration `boiler_heat_demand`: switch a gas boiler relay from thermostatic valve (`climate`) heat demand. Repo `bartosekpetr/ha-boiler-heat-demand`, MIT, HACS.

- `demand.py`: pure logic, no HA imports, unit-tested.
- `controller.py`: state listeners + relay switching. `config_flow.py`, `binary_sensor.py`, `sensor.py`: HA glue (not covered by tests).
- Keep `strings.json` and `translations/en.json` identical; update README on behaviour changes.
- Run `py -3 -m pytest -q tests` and `py -3 -m compileall -q custom_components tests` before commits.
- Commits: author `bartosekpetr`, end with `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`.
