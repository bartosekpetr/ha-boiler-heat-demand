# v0.6.0

A dashboard that builds itself, and a card-loading failure that explains itself. Nothing in the heating decision path changed — `demand.py`, `controller.py`, `learning.py` and `devices.py` are untouched by this release.

## New

- **An instant boiler dashboard.** The integration now ships a Lovelace dashboard strategy. Paste two lines into a new dashboard's raw configuration editor and it builds itself from the Home Assistant registries — the card, a plain-text banner for alerts and the low-temperature safety state, and a list of the supporting entities. No entity ids to type, which also means it works on installs whose entity ids predate the device grouping.

  ```yaml
  strategy:
    type: custom:boiler-heat-demand
  ```

  It does **not** appear in the *Add dashboard* picker — Home Assistant has no registry through which a custom strategy can advertise itself, so the two lines are unavoidable. With several boilers configured each gets its own view; with none it shows an explanatory note instead of an error.

- **Reset learning, on the generated dashboard but behind a confirmation.** It sits in its own *Maintenance* section rather than in the details list, and asks before it erases every room's learned heating behaviour.

## Fixes

- **A missing card file now reports itself instead of showing a red box.** If the card's JS is not on disk, Home Assistant raises a *Boiler dashboard card file is missing* repair notice, and start-up logs the exact URL the card was registered at. Setting up the integration still succeeds either way: a dashboard file must never stop the boiler being controlled.
- **The card URL carries the installed version**, so the browser's network tab shows which copy it actually loaded. One case remains outside the integration's reach: the page listing the card files is cached by the browser itself, and a browser holding a stale copy never sees a changed entry. Reloading without cache is the fix, and the README says so.

## Upgrading

No configuration changes, and no change to how heat is requested. **Restart Home Assistant after updating** — a reload is not enough to register the card or the strategy.

Existing dashboards are untouched. Both the card and the strategy are opt-in, and the YAML-only recipe in the README still works for anyone who would rather not load a custom module.

## Verifying on your own installation

93 tests pass, and the status banner's template is now rendered through Home Assistant's own template engine in CI rather than only read — the generated dashboard is driven through its real `generate()` and every branch of the banner is asserted. Also covered: the card file is served once, a config-entry reload does not register it twice, and two config entries do not double-register.

What tests still cannot cover is appearance. Worth a look: the dashboard builds without a *Timeout waiting for strategy* error, the banner reads ✅ *No boiler alerts* on a healthy install, and light/dark contrast and phone-width layout are acceptable.

The check still worth doing from 0.4.0: with heat demanded and the relay on, restart Home Assistant and confirm the relay stays on, or returns on without a five-minute gap.

This integration only requests heat from a relay; keep the boiler's own safety controls in place.
