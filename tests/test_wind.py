"""Tests for wind observation parsing, vector grid interpolation, and particle simulation."""

import io
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from custom_components.nl_weather.camera import WindParticlesCam
from custom_components.nl_weather.KNMI.wind import (
    WindObservation,
    WindParticleEngine,
    WindVectorGrid,
    degrees_to_compass,
    parse_edr_wind_coverages,
    speed_to_bft,
    speed_to_color,
)


def test_degrees_to_compass():
    """Test degrees conversion to 16-point compass directions."""
    assert degrees_to_compass(0) == "N"
    assert degrees_to_compass(360) == "N"
    assert degrees_to_compass(45) == "NE"
    assert degrees_to_compass(90) == "E"
    assert degrees_to_compass(135) == "SE"
    assert degrees_to_compass(180) == "S"
    assert degrees_to_compass(225) == "SW"
    assert degrees_to_compass(270) == "W"
    assert degrees_to_compass(315) == "NW"
    assert degrees_to_compass(350) == "N"


def test_speed_to_bft():
    """Test m/s to Beaufort scale conversions."""
    assert speed_to_bft(0.1) == 0
    assert speed_to_bft(1.0) == 1
    assert speed_to_bft(2.5) == 2
    assert speed_to_bft(4.0) == 3
    assert speed_to_bft(6.5) == 4
    assert speed_to_bft(9.0) == 5
    assert speed_to_bft(12.0) == 6
    assert speed_to_bft(15.0) == 7
    assert speed_to_bft(18.5) == 8
    assert speed_to_bft(22.0) == 9
    assert speed_to_bft(26.0) == 10
    assert speed_to_bft(30.0) == 11
    assert speed_to_bft(35.0) == 12


def test_speed_to_color():
    """Test wind speed to color mapping."""
    color_calm = speed_to_color(2.0, alpha=200)
    assert color_calm[3] == 200
    assert color_calm[0] < 150  # Cyan/blue

    color_fresh = speed_to_color(8.0, alpha=150)
    assert color_fresh[3] == 150
    assert color_fresh[1] > 200  # Greenish

    color_gale = speed_to_color(20.0, alpha=255)
    assert color_gale[3] == 255
    assert color_gale[0] > 200  # Reddish/orange


def test_parse_edr_wind_coverages():
    """Test parsing EDR coverage collection into observations."""
    sample_coverages = [
        {
            "eumetnet:locationId": "06240",
            "domain": {
                "axes": {
                    "x": {"values": [4.79]},  # Schiphol lon
                    "y": {"values": [52.31]},  # Schiphol lat
                }
            },
            "ranges": {
                "dd": {"values": [260.0, 270.0]},  # From due West
                "ff": {"values": [9.0, 10.0]},  # 10 m/s
            },
        },
        {
            # Caribbean station (should be filtered out)
            "eumetnet:locationId": "caribbean_1",
            "domain": {
                "axes": {
                    "x": {"values": [-68.2]},
                    "y": {"values": [12.1]},
                }
            },
            "ranges": {"dd": {"values": [90.0]}, "ff": {"values": [5.0]}},
        },
        {
            # Missing data (should be skipped)
            "eumetnet:locationId": "empty_station",
            "domain": {"axes": {"x": {"values": [5.0]}, "y": {"values": [52.0]}}},
            "ranges": {"dd": {"values": [None]}, "ff": {"values": [None]}},
        },
    ]

    observations = parse_edr_wind_coverages(sample_coverages)
    assert len(observations) == 1

    obs = observations[0]
    assert obs.station_id == "06240"
    assert obs.speed == 10.0
    assert obs.direction == 270.0
    # Wind FROM 270 (West) blows TOWARDS East: u = +10, v = 0
    assert pytest.approx(obs.u, abs=1e-3) == 10.0
    assert pytest.approx(obs.v, abs=1e-3) == 0.0


def test_wind_vector_grid_interpolation():
    """Test 2D IDW interpolation of wind vectors."""
    obs1 = WindObservation(
        station_id="1",
        lon=4.8,
        lat=52.3,
        x=534335.0,
        y=6854652.0,
        speed=10.0,
        direction=270.0,
        u=10.0,
        v=0.0,
    )
    obs2 = WindObservation(
        station_id="2",
        lon=4.9,
        lat=52.4,
        x=545468.0,
        y=6872658.0,
        speed=10.0,
        direction=270.0,
        u=10.0,
        v=0.0,
    )

    bbox = (530000.0, 6850000.0, 550000.0, 6880000.0)
    grid = WindVectorGrid([obs1, obs2], bbox, grid_w=10, grid_h=10)

    assert pytest.approx(grid.mean_speed, abs=0.1) == 10.0
    assert pytest.approx(grid.mean_direction, abs=1.0) == 270.0

    # Test velocity lookup at center
    u, v_screen = grid.get_velocity_at(300, 300, 600, 600)
    assert pytest.approx(u, abs=0.1) == 10.0
    assert pytest.approx(v_screen, abs=0.1) == 0.0


def test_wind_particle_engine_rendering():
    """Test generating animated GIF from particle engine."""
    obs = WindObservation(
        station_id="1",
        lon=4.8,
        lat=52.3,
        x=534335.0,
        y=6854652.0,
        speed=5.0,
        direction=225.0,  # SW wind
        u=3.53,
        v=3.53,
    )
    bbox = (530000.0, 6850000.0, 550000.0, 6880000.0)
    grid = WindVectorGrid([obs], bbox, grid_w=10, grid_h=10)

    engine = WindParticleEngine(
        grid=grid,
        canvas_size=(200, 200),
        n_particles=50,
        n_frames=10,
        frame_duration_ms=50,
    )

    base = Image.new("RGBA", (200, 200), (20, 20, 20, 255))
    gif_bytes = engine.render_animation(
        base,
        timestamp=datetime(2026, 10, 29, 10, 0, tzinfo=timezone.utc),
    )

    assert isinstance(gif_bytes, bytes)
    assert len(gif_bytes) > 1000
    # Must be valid GIF file
    assert gif_bytes[:4] == b"GIF8"

    # Verify PIL can reopen it
    gif_img = Image.open(io.BytesIO(gif_bytes))
    assert gif_img.format == "GIF"
    assert gif_img.is_animated
    assert gif_img.n_frames == 10


@pytest.mark.asyncio
async def test_wind_camera_entity_image(monkeypatch):
    """Test WindParticlesCam entity image generation with mock EDR."""
    mock_edr = MagicMock()
    mock_edr.get_wind_observations = AsyncMock(
        return_value=[
            {
                "eumetnet:locationId": "06240",
                "domain": {
                    "axes": {
                        "x": {"values": [4.79]},
                        "y": {"values": [52.31]},
                    }
                },
                "ranges": {
                    "dd": {"values": [220.0]},
                    "ff": {"values": [4.5]},
                },
            }
        ]
    )

    mock_entry = MagicMock()
    mock_entry.entry_id = "test_entry"
    mock_entry.options = {}
    mock_entry.subentries = {}
    mock_entry.runtime_data.edr = mock_edr
    mock_entry.runtime_data.notification_service.set_callback = MagicMock()

    cam = WindParticlesCam(mock_entry)
    cam.hass = MagicMock()
    cam.hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    # Set dummy base map
    cam._background_image = Image.new("RGBA", (200, 200), (30, 30, 30, 255))
    cam._radar_bbox = (0.0, 6300000, 1000000, 7300000)

    # Mock async_ensure_background to do nothing
    cam.async_ensure_background = AsyncMock()

    img_bytes = await cam.async_camera_image()

    assert img_bytes is not None
    assert img_bytes[:4] == b"GIF8"
    assert cam._attr_unique_id == "test_entry_wind_particles"
    assert cam._attr_translation_key == "wind_particles"
