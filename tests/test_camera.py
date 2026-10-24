"""Tests for NL Weather camera platform."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.nl_weather.camera import PrecipitationRadarCam
from custom_components.nl_weather.KNMI.helpers import Coordinate


def test_camera_locations_dynamic_update() -> None:
    """Test that camera._locations dynamically updates when subentries are added or removed."""
    config_entry = MagicMock()
    config_entry.entry_id = "test_entry"
    config_entry.options = {}

    subentry1 = MagicMock()
    subentry1.data = {"latitude": 52.0, "longitude": 4.5}

    config_entry.subentries = {"sub1": subentry1}

    cam = PrecipitationRadarCam(config_entry)
    assert cam._locations == [Coordinate(52.0, 4.5)]

    # Add a second subentry dynamically
    subentry2 = MagicMock()
    subentry2.data = {"latitude": 51.5, "longitude": 5.0}
    config_entry.subentries["sub2"] = subentry2

    assert cam._locations == [Coordinate(52.0, 4.5), Coordinate(51.5, 5.0)]

    # Remove the first subentry dynamically
    del config_entry.subentries["sub1"]
    assert cam._locations == [Coordinate(51.5, 5.0)]


@pytest.mark.asyncio
async def test_camera_config_entry_update_listener() -> None:
    """Test that config entry update listener rebuilds background and invalidates cached image."""
    config_entry = MagicMock()
    config_entry.entry_id = "test_entry"
    config_entry.options = {"radar_style": "light", "mark_locations": True}
    config_entry.subentries = {}

    cam = PrecipitationRadarCam(config_entry)
    cam.hass = MagicMock()
    cam.hass.async_add_executor_job = AsyncMock(side_effect=lambda func: func())
    cam._last_image_dt = datetime.now(UTC)

    await cam._async_on_config_entry_update(cam.hass, config_entry)

    # Verify cached image timestamp was invalidated
    assert cam._last_image_dt is None
    # Verify executor job was called to reload background
    cam.hass.async_add_executor_job.assert_called_once_with(cam._load_background)
