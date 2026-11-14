"""Tests for KNMI nationwide warnings API and coordinator error behavior."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.nl_weather.coordinator import NLWeatherAlertsCoordinator
from custom_components.nl_weather.KNMI.app import App, NotFoundError


@pytest.mark.asyncio
async def test_nationwide_warnings_endpoint() -> None:
    """Fetch the dedicated nationwide warning resource."""
    app = App(MagicMock())
    app.get = AsyncMock(return_value={"warnings": []})
    assert await app.alerts_nationwide() == {"warnings": []}
    app.get.assert_awaited_once_with("alerts/nationwide")


def _coordinator() -> NLWeatherAlertsCoordinator:
    """Build a nationwide coordinator with a mocked KNMI client."""
    hass = MagicMock()
    entry = MagicMock()
    entry.title = "Test"
    entry.runtime_data.app = MagicMock()
    return NLWeatherAlertsCoordinator(hass, entry)


@pytest.mark.asyncio
async def test_empty_nationwide_warnings_response() -> None:
    """Accept a genuine empty warning list without losing coordinator state."""
    coordinator = _coordinator()
    coordinator._api.alerts_nationwide = AsyncMock(return_value={"warnings": []})
    assert await coordinator._async_update_data() == []


@pytest.mark.asyncio
async def test_coordinator_rejects_malformed_response() -> None:
    """Raise UpdateFailed instead of publishing a misleading all-clear state."""
    coordinator = _coordinator()
    coordinator._api.alerts_nationwide = AsyncMock(return_value={"wrong": []})
    with pytest.raises(UpdateFailed, match="valid nationwide"):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_coordinator_preserves_api_failure_context() -> None:
    """Map KNMI endpoint failures onto Home Assistant coordinator failures."""
    coordinator = _coordinator()
    coordinator._api.alerts_nationwide = AsyncMock(
        side_effect=NotFoundError("No warnings endpoint")
    )
    with pytest.raises(UpdateFailed) as raised:
        await coordinator._async_update_data()
    assert isinstance(raised.value.__cause__, NotFoundError)
