"""The dashboard card is served by the integration; registration must happen once per start."""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

if sys.platform == "win32":
    pytest.skip(
        "Home Assistant integration tests run on Linux in CI", allow_module_level=True
    )

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.boiler_heat_demand as integration
from custom_components.boiler_heat_demand import CARD_FILE, CARD_URL, async_setup
from custom_components.boiler_heat_demand.const import DOMAIN

MANIFEST = Path(integration.__file__).parent / "manifest.json"
STAMPED_URL = (
    f"{CARD_URL}?v={json.loads(MANIFEST.read_text(encoding='utf-8'))['version']}"
)
ISSUE = (DOMAIN, "card_file_missing")


def _card_routes(hass):
    return [
        r
        for r in hass.http.app.router.routes()
        if r.method == "GET" and r.resource and r.resource.canonical == CARD_URL
    ]


@pytest.fixture(autouse=True)
async def serving(hass):
    """Real `http` (the route registry under test); `frontend` is stubbed.

    The frontend component needs the `home-assistant-frontend` package, which the
    test requirements do not install, so only its JS-URL hook is observed.
    """
    assert await async_setup_component(hass, "http", {})
    hass.config.components.add("frontend")
    with patch(
        "custom_components.boiler_heat_demand.add_extra_js_url", new=MagicMock()
    ) as add_js:
        yield add_js


@pytest.fixture
def no_controller():
    """Set up entries without starting the real controller (not under test here)."""
    with (
        patch(
            "custom_components.boiler_heat_demand.BoilerController.async_load",
            new=AsyncMock(),
        ),
        patch("custom_components.boiler_heat_demand.BoilerController.start"),
        patch("custom_components.boiler_heat_demand.BoilerController.stop"),
        patch(
            "custom_components.boiler_heat_demand.PLATFORMS",
            [],
        ),
    ):
        yield


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_card_file_exists_at_registered_path(hass):
    assert await async_setup_component(hass, DOMAIN, {})
    assert await hass.async_add_executor_job(CARD_FILE.is_file)
    assert CARD_FILE.name == CARD_URL.rsplit("/", 1)[1]
    assert len(_card_routes(hass)) == 1


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_setup_registers_once(hass, serving):
    assert await async_setup_component(hass, DOMAIN, {})
    assert len(_card_routes(hass)) == 1
    assert serving.call_args_list == [call(hass, STAMPED_URL)]


@pytest.mark.usefixtures("enable_custom_integrations", "no_controller")
async def test_entry_reload_does_not_re_register(hass, serving):
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert len(_card_routes(hass)) == 1
    assert serving.call_args_list == [call(hass, STAMPED_URL)]


@pytest.mark.usefixtures("enable_custom_integrations", "no_controller")
async def test_two_entries_do_not_double_register(hass, serving):
    first = MockConfigEntry(domain=DOMAIN, data={}, title="one")
    second = MockConfigEntry(domain=DOMAIN, data={}, title="two")
    first.add_to_hass(hass)
    second.add_to_hass(hass)
    assert await hass.config_entries.async_setup(first.entry_id)
    # Setting up the first entry sets up the domain, which loads every entry of it.
    await hass.async_block_till_done()

    assert first.state is ConfigEntryState.LOADED
    assert second.state is ConfigEntryState.LOADED
    assert len(_card_routes(hass)) == 1
    assert serving.call_args_list == [call(hass, STAMPED_URL)]


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_present_file_stamps_url_and_raises_no_issue(hass, serving):
    assert await async_setup_component(hass, DOMAIN, {})
    assert len(_card_routes(hass)) == 1
    assert serving.call_args_list == [call(hass, STAMPED_URL)]
    assert "?v=" in STAMPED_URL
    assert ir.async_get(hass).async_get_issue(*ISSUE) is None


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_present_file_logs_url_and_restart_hint(hass, caplog):
    caplog.set_level("INFO", logger="custom_components.boiler_heat_demand")
    assert await async_setup_component(hass, DOMAIN, {})
    assert STAMPED_URL in caplog.text
    assert "restart" in caplog.text.lower()


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_missing_file_still_sets_up_and_raises_issue(hass, serving, tmp_path):
    with patch.object(integration, "CARD_FILE", tmp_path / "gone.js"):
        assert await async_setup_component(hass, DOMAIN, {})

    assert _card_routes(hass) == []
    serving.assert_not_called()
    issue = ir.async_get(hass).async_get_issue(*ISSUE)
    assert issue is not None
    assert issue.translation_key == "card_file_missing"
    assert issue.is_fixable is False


@pytest.mark.usefixtures("enable_custom_integrations", "no_controller")
async def test_missing_file_does_not_stop_config_entries(hass, tmp_path):
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    with patch.object(integration, "CARD_FILE", tmp_path / "gone.js"):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_issue_clears_once_file_is_back(hass, serving, tmp_path):
    with patch.object(integration, "CARD_FILE", tmp_path / "gone.js"):
        assert await async_setup_component(hass, DOMAIN, {})
    assert ir.async_get(hass).async_get_issue(*ISSUE) is not None

    # Same start-up path a later Home Assistant start takes, with the file restored.
    assert await async_setup(hass, {})

    assert ir.async_get(hass).async_get_issue(*ISSUE) is None
    assert len(_card_routes(hass)) == 1
    assert serving.call_args_list == [call(hass, STAMPED_URL)]
