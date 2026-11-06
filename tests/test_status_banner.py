"""The generated dashboard's status banner is a Jinja template, so render it.

Nothing else in CI executes it. A template that is merely *read* can be wrong in
ways that look fine: the YAML fallback snippet shipped an always-true condition
that showed an empty alert banner permanently. So the real shipped template is
pulled out of the JS through the strategy's own `generate()` (via node) and run
through Home Assistant's template engine, rather than copied into this file
where it would quietly drift.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

if sys.platform == "win32":
    pytest.skip(
        "Home Assistant integration tests run on Linux in CI", allow_module_level=True
    )

from homeassistant.helpers.template import Template

ENTITY = "binary_sensor.automated_boiler_heat_demand"
HARNESS = Path(__file__).parent / "js" / "dashboard_config.mjs"


def _dashboard():
    """The dashboard config the shipped strategy really generates."""
    node = shutil.which("node")
    if node is None:  # pragma: no cover - CI runners have node
        pytest.skip("node is required to read the shipped strategy output")
    out = subprocess.run(
        [node, str(HARNESS), ENTITY],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert out.returncode == 0, f"strategy harness failed:\n{out.stderr}"
    return json.loads(out.stdout)


@pytest.fixture(name="banner", scope="module")
def banner_fixture():
    """The status banner's template text, as the dashboard would render it."""
    cards = _dashboard()["views"][0]["cards"]
    banners = [
        c["content"]
        for c in cards
        if c.get("type") == "markdown" and "{%" in c.get("content", "")
    ]
    assert len(banners) == 1, f"expected 1 templated markdown card, got {len(banners)}"
    return banners[0]


async def _render(hass, banner, state, **attributes):
    if state is not None:
        hass.states.async_set(ENTITY, state, attributes)
        await hass.async_block_till_done()
    return Template(banner, hass).async_render(parse_result=False)


async def test_healthy_boiler_reports_no_alerts(hass, banner):
    """The common case: an empty alert list must not read as an alert."""
    out = await _render(hass, banner, "on", alerts=[], safety_override=False)
    assert "No boiler alerts" in out
    assert "🚨" not in out
    assert "Low-temperature safety active" not in out


async def test_missing_alerts_attribute_does_not_error(hass, banner):
    """`None` must not reach the loop; `or []` is what guards it."""
    out = await _render(hass, banner, "off")
    assert "No boiler alerts" in out
    assert "None" not in out


async def test_alerts_are_listed_and_humanised(hass, banner):
    out = await _render(
        hass, banner, "on", alerts=["stuck_relay", "service_call_failed"]
    )
    assert "🚨 Boiler alerts" in out
    assert "**Stuck relay**" in out
    assert "**Service call failed**" in out
    assert "No boiler alerts" not in out


async def test_safety_override_is_shown_alongside_alerts(hass, banner):
    """Frost protection forcing the relay on must never be rendered as silence."""
    out = await _render(
        hass, banner, "on", alerts=["stuck_relay"], safety_override=True
    )
    assert "Low-temperature safety active" in out
    assert "being kept heating" in out
    assert "🚨 Boiler alerts" in out


async def test_unavailable_entity_says_so(hass, banner):
    out = await _render(hass, banner, "unavailable")
    assert "Boiler status unavailable" in out
    assert "No boiler alerts" not in out


async def test_absent_entity_does_not_claim_health(hass, banner):
    """With no entity at all, `states()` is unknown - not "no alerts"."""
    out = await _render(hass, banner, None)
    assert "No boiler alerts" not in out
    assert "Boiler status unknown" in out


def test_reset_learning_is_confirmed_and_out_of_the_details_list():
    """Wiping learned data must not be one unguarded tap on a generated view."""
    cards = _dashboard()["views"][0]["cards"]
    by_title = {c.get("title"): c for c in cards if c.get("type") == "entities"}

    maintenance = by_title["Maintenance"]
    (row,) = maintenance["entities"]
    assert row["entity"].startswith("button.")
    assert row["entity"].endswith("reset_learning")
    assert row["confirmation"]["text"]

    details = json.dumps(by_title["Details"])
    assert "reset_learning" not in details
