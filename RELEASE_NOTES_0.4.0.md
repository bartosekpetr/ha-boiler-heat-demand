# v0.4.0

The first release of this integration without a beta label. Two behavioural fixes in the heating decision path are why this is a minor bump rather than a patch.

1.0.0 is deliberately not proposed: the config/options schema was still changing as recently as 0.3.0-beta.7 (area-based room detection), so a stability promise is premature.

## Fixes

- **A manual OFF no longer disables frost protection.** Switching the boiler control off by hand used to also stop the low-temperature safety; it now keeps working.
- **Restarts no longer interrupt running heat for five minutes.** After restarting Home Assistant (or reloading the integration) while the boiler was heating, the relay was held off for the minimum-off time. A running call for heat now continues across restarts.

## Also in this release

- Prepared for the Home Assistant 2026.11 Marketplace: the manifest declares a `categories` entry and the README documents Marketplace install alongside the existing HACS route.
- Validation (lint, tests, hassfest, HACS) now also runs nightly, so a breaking change in Home Assistant core surfaces here rather than in a bug report.
- Repaired double-encoded UTF-8 in the README, which had mangled the dashes, degree signs and comparison operators in the sections describing when heat is requested.

## Upgrading

No configuration changes. Existing installations keep working.

## Verifying on your own installation

Both fixes are covered by the test suite (84 tests). The check worth doing after upgrading: with heat demanded and the relay on, restart Home Assistant and confirm the relay stays on, or returns on without a five-minute gap.

This integration only requests heat from a relay; keep the boiler's own safety controls in place.
