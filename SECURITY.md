# Security policy

## Reporting a vulnerability

Please report security issues privately through GitHub: **Security → Report a vulnerability** on
<https://github.com/bartosekpetr/ha-boiler-heat-demand/security/advisories/new>.
Do not open a public issue for anything that could let someone switch a boiler unsafely.

## Scope

This integration only requests heat through a relay you configure. It does not replace the boiler's own
safety controls. Issues in scope include logic that could leave the relay stuck on or off, bypass the
minimum on/off times or the low-temperature safety, unsafe handling of entity states or stored data, and
problems in the build/release pipeline.

## Supported versions

Only the latest release (including pre-releases) receives fixes.
