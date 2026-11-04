# Contributing

Thanks for helping. Bug reports, feature ideas and pull requests are all welcome.

## Reporting problems

- **Bugs and feature requests:** open an issue and fill in the form (HA version, integration version, relevant log lines).
- **Security issues:** do **not** open a public issue. Use GitHub's private route: **Security → Report a vulnerability**, or <https://github.com/bartosekpetr/ha-boiler-heat-demand/security/advisories/new>. See [SECURITY.md](SECURITY.md). This integration switches a boiler relay, so anything that could leave it stuck on or off counts.

## Development environment

You need Python 3.14 (what CI uses; the pinned `pytest-homeassistant-custom-component` determines which versions work) and git. No running Home Assistant is needed for the tests.

```bash
git clone https://github.com/bartosekpetr/ha-boiler-heat-demand
cd ha-boiler-heat-demand
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m pip install -r requirements-test.txt
```

To try changes in a real Home Assistant, copy or symlink `custom_components/boiler_heat_demand` into your HA `config/custom_components/` folder and restart HA. Logs: Settings → System → Logs.

## Tests

```bash
python -m pytest -q tests
python -m compileall -q custom_components tests
```

CI (`.github/workflows/validate.yml`) runs the same two commands plus `hassfest` and the HACS validation. Pure decision logic lives in `demand.py` and `learning.py` and is tested directly; please add a test with any behaviour change, in `tests/test_demand.py`, `tests/test_learning.py` or `tests/test_ha_glue.py` as fits.

## Lint and style

There is no linter configured in the repo yet, so there is nothing to satisfy beyond CI. Match the surrounding code (type hints, short functions, no new dependencies). If you run `ruff` locally, please keep changes focused rather than reformatting untouched code.

## Pull requests

- Keep each PR to one change; explain the behaviour change in the description.
- Make sure the tests above pass.
- Bump `manifest.json` `version` only if you are cutting a release (maintainer's call).
- Dependabot PRs are maintainer-handled.

By contributing you agree your work is released under the repository's [LICENSE](LICENSE).
