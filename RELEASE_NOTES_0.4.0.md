# v0.4.0 (draft release notes)

First release without the beta label. Eight betas and no reported bugs; the two behavioural fixes below are why this is a minor bump (0.4.0) rather than a patch. 1.0.0 is deliberately not proposed: the config/options schema was still changing as recently as beta.7 (area-based room detection), so a stability promise is premature.

## Fixes

- **A manual OFF no longer disables frost protection.** Switching the boiler control off by hand used to also stop the low-temperature safety; it now keeps working.
- **Restarts no longer interrupt running heat for five minutes.** After restarting Home Assistant (or reloading the integration) while the boiler was heating, the relay was held off for the minimum-off time. A running call for heat now continues across restarts.

## Upgrading

No configuration changes. Existing installations keep working.

## Before tagging

With 0 stars, field testing across restarts is thin. Please do a real-install check of the restart fix first: with heat demanded and the relay on, restart Home Assistant and confirm the relay stays on (or returns on without a five-minute gap).
