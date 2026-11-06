# v0.5.0

A dashboard card, shipped inside the integration. A minor bump rather than a patch because the integration now serves a frontend file and declares two new dependencies; nothing in the heating decision path changed.

## New

- **A Lovelace card, with nothing extra to install.** The integration serves its own card, so it appears in the dashboard card picker as *Boiler Heat Demand* after a restart and can be configured from the UI. It shows whether the boiler is calling for heat, any active alerts, and the low-temperature safety state.
- **One Auto / On / Off control instead of three buttons.** Setting an override previously meant finding one of three separate button entities. The card presents them as a single three-way control and presses the same buttons underneath. An active override shows its remaining time, or "until you resume" when the manual timeout is `0`.
- Sibling entities (the buttons and the metric sensors) are resolved from the same device as the configured sensor, so no entity ids need to be filled in. A control whose entity cannot be found is hidden rather than breaking the card.

## Fixes

- **The README described frost protection backwards.** It said a manual OFF takes precedence over the low-temperature safety override. That stopped being true in 0.4.0, where frost protection was fixed to win over a manual OFF, and the same file contradicted itself seven lines later. The sentence is corrected, and the card's safety banner now says that frost protection is overriding the manual OFF and the boiler is being kept heating.
- **The YAML-only fallback recipe in the README showed its alert card permanently.** The conditional used `state_not: []`, which Lovelace evaluates as always true. Corrected, and the alert card is now hidden when there are no alerts and when the sensor is unavailable.

## Upgrading

No configuration changes, and no change to how heat is requested. **Restart Home Assistant after updating** — a reload is not enough for the card to register.

Existing dashboards are untouched; the card is opt-in. The YAML-only recipe in the README remains available for anyone who would rather not load a custom module.

## Verifying on your own installation

The registration path is covered by tests (88 in total): the card file is served once, a config-entry reload does not register it twice, and two config entries do not double-register. What tests cannot cover is appearance — light and dark contrast, phone-width layout, and that the Auto / On / Off control resolves its buttons on your install.

The check still worth doing from 0.4.0: with heat demanded and the relay on, restart Home Assistant and confirm the relay stays on, or returns on without a five-minute gap.

This integration only requests heat from a relay; keep the boiler's own safety controls in place.
