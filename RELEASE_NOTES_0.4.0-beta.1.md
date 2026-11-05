# v0.4.0-beta.1 (draft release notes)

A prerelease, like the eight before it. The two behavioural fixes below are why this is a minor bump (0.4.0) rather than a patch, and the `-beta.1` suffix is there because neither fix has run on a real Home Assistant yet. A stable 0.4.0 follows once the restart fix has been confirmed on hardware. 1.0.0 is deliberately not proposed: the config/options schema was still changing as recently as beta.7 (area-based room detection), so a stability promise is premature.

## Fixes

- **A manual OFF no longer disables frost protection.** Switching the boiler control off by hand used to also stop the low-temperature safety; it now keeps working.
- **Restarts no longer interrupt running heat for five minutes.** After restarting Home Assistant (or reloading the integration) while the boiler was heating, the relay was held off for the minimum-off time. A running call for heat now continues across restarts.

## Upgrading

No configuration changes. Existing installations keep working.

## Not yet verified on hardware

Both fixes are covered by tests, and nothing here has run on a live installation. The check worth doing first: with heat demanded and the relay on, restart Home Assistant and confirm the relay stays on (or returns on without a five-minute gap).
