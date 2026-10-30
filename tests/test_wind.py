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
    create_app_target_wind_observation,
    decode_app_wind_speed_color,
    decode_wms_wind_speed_color,
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


def test_create_app_target_wind_observation():
    """Test creating WindObservation from App API wind dictionary."""
    # Speed is in km/h: 36 km/h = 10 m/s
    wind_data = {
        "source": "W",
        "degree": 270.0,
        "speed": 36.0,
        "gusts": 50,
        "beaufort": 5,
    }
    obs = create_app_target_wind_observation(
        station_id="app_target_1",
        lat=52.37,
        lon=4.89,
        wind_data=wind_data,
    )
    assert obs is not None
    assert obs.station_id == "app_target_1"
    assert pytest.approx(obs.speed, abs=1e-2) == 10.0
    assert obs.direction == 270.0
    # From West (270) -> blows East (u = +10, v = 0)
    assert pytest.approx(obs.u, abs=1e-2) == 10.0
    assert pytest.approx(obs.v, abs=1e-2) == 0.0
    assert obs.lat == 52.37
    assert obs.lon == 4.89
    assert obs.x > 0
    assert obs.y > 0

    # Test invalid / missing values
    assert create_app_target_wind_observation("app_target_1", 52.37, 4.89, None) is None
    assert create_app_target_wind_observation("app_target_1", 52.37, 4.89, {}) is None
    assert (
        create_app_target_wind_observation(
            "app_target_1", 52.37, 4.89, {"speed": None, "degree": 180}
        )
        is None
    )
    assert (
        create_app_target_wind_observation(
            "app_target_1", 52.37, 4.89, {"speed": 20, "degree": "invalid"}
        )
        is None
    )
    # Coordinates outside NL
    assert (
        create_app_target_wind_observation(
            "app_target_1", 12.0, -68.0, {"speed": 20, "degree": 180}
        )
        is None
    )


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
    cam.hass.async_add_executor_job = AsyncMock(
        side_effect=lambda func, *args: func(*args)
    )

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


@pytest.mark.asyncio
async def test_camera_async_setup_entry_selection():
    """Test camera platform async_setup_entry maps selection."""
    from custom_components.nl_weather.camera import async_setup_entry

    mock_entry = MagicMock()
    mock_entry.entry_id = "test_entry"
    mock_entry.subentries = {}
    mock_entry.runtime_data = MagicMock()

    # Test all three enabled
    mock_entry.options = {"enabled_maps": ["precipitation", "wind", "hybrid"]}
    added_entities = []
    await async_setup_entry(
        MagicMock(), mock_entry, lambda ents: added_entities.extend(ents)
    )
    assert len(added_entities) == 3
    keys = [e._attr_translation_key for e in added_entities]
    assert "precipitation_radar" in keys
    assert "wind_particles" in keys
    assert "hybrid_weather" in keys

    # Test only hybrid
    mock_entry.options = {"enabled_maps": ["hybrid"]}
    added_entities.clear()
    await async_setup_entry(
        MagicMock(), mock_entry, lambda ents: added_entities.extend(ents)
    )
    assert len(added_entities) == 1
    assert added_entities[0]._attr_translation_key == "hybrid_weather"


@pytest.mark.asyncio
async def test_hybrid_camera_entity_image():
    """Test HybridWeatherCam entity image generation with mock EDR and WMS."""
    from custom_components.nl_weather.camera import HybridWeatherCam

    mock_edr = MagicMock()
    mock_edr.get_wind_observations = AsyncMock(
        return_value=[
            {
                "eumetnet:locationId": "06240",
                "domain": {"axes": {"x": {"values": [4.79]}, "y": {"values": [52.31]}}},
                "ranges": {"dd": {"values": [220.0]}, "ff": {"values": [4.5]}},
            }
        ]
    )

    mock_wms = MagicMock()
    radar_buf = io.BytesIO()
    Image.new("RGBA", (200, 200), (0, 0, 0, 0)).save(radar_buf, format="PNG")
    mock_wms.radar_forecast_image = AsyncMock(return_value=radar_buf)

    mock_entry = MagicMock()
    mock_entry.entry_id = "test_entry"
    mock_entry.options = {}
    mock_entry.subentries = {}
    mock_entry.runtime_data.edr = mock_edr
    mock_entry.runtime_data.wms = mock_wms
    mock_entry.runtime_data.notification_service.set_callback = MagicMock()

    cam = HybridWeatherCam(mock_entry)
    cam.hass = MagicMock()
    cam.hass.async_add_executor_job = AsyncMock(
        side_effect=lambda func, *args: func(*args)
    )
    cam._background_image = Image.new("RGBA", (200, 200), (30, 30, 30, 255))
    cam._radar_bbox = (0.0, 6300000, 1000000, 7300000)
    cam.async_ensure_background = AsyncMock()
    cam._latest_radar_datetime = AsyncMock(
        return_value=datetime(2026, 10, 29, 14, 0, tzinfo=timezone.utc)
    )

    img_bytes = await cam.async_camera_image()

    assert img_bytes is not None
    assert img_bytes[:4] == b"GIF8"
    assert cam._attr_unique_id == "test_entry_hybrid_weather"
    assert cam._attr_translation_key == "hybrid_weather"


@pytest.mark.asyncio
async def test_wind_camera_mixes_app_target_wind():
    """Test that WindParticlesCam mixes in local App API target observation."""
    mock_edr = MagicMock()
    mock_edr.get_wind_observations = AsyncMock(
        return_value=[
            {
                "eumetnet:locationId": "06240",
                "domain": {"axes": {"x": {"values": [4.79]}, "y": {"values": [52.31]}}},
                "ranges": {"dd": {"values": [180.0]}, "ff": {"values": [5.0]}},
            }
        ]
    )

    mock_subentry = MagicMock()
    mock_subentry.data = {
        "latitude": 52.37,
        "longitude": 4.89,
    }

    mock_app_coord = MagicMock()
    mock_app_coord.data = {
        "wind": {
            "speed": 21.6,  # 6.0 m/s
            "degree": 270.0,
        }
    }

    mock_entry = MagicMock()
    mock_entry.entry_id = "test_entry"
    mock_entry.options = {}
    mock_entry.subentries = {"sub_1": mock_subentry}
    mock_entry.runtime_data.edr = mock_edr
    mock_entry.runtime_data.app_coordinators = {"sub_1": mock_app_coord}
    mock_entry.runtime_data.notification_service.set_callback = MagicMock()

    cam = WindParticlesCam(mock_entry)
    cam.hass = MagicMock()
    cam.hass.async_add_executor_job = AsyncMock(
        side_effect=lambda func, *args: func(*args)
    )
    cam._background_image = Image.new("RGBA", (200, 200), (30, 30, 30, 255))
    cam._radar_bbox = (0.0, 6300000, 1000000, 7300000)
    cam.async_ensure_background = AsyncMock()

    target_obs = cam._get_target_wind_observations()
    assert len(target_obs) == 1
    assert target_obs[0].station_id == "app_target_sub_1"
    assert pytest.approx(target_obs[0].speed, abs=0.1) == 6.0
    assert target_obs[0].direction == 270.0

    img_bytes = await cam.async_camera_image()
    assert img_bytes is not None
    assert img_bytes[:4] == b"GIF8"


@pytest.mark.asyncio
async def test_wind_camera_edr_failure_fallback_to_app_target():
    """Test that WindParticlesCam recovers and renders when EDR fails but App API target data is available."""
    from custom_components.nl_weather.KNMI.edr import ServerError

    mock_edr = MagicMock()
    mock_edr.get_wind_observations = AsyncMock(side_effect=ServerError("KNMI EDR down"))

    mock_subentry = MagicMock()
    mock_subentry.data = {
        "latitude": 52.37,
        "longitude": 4.89,
    }

    mock_app_coord = MagicMock()
    mock_app_coord.data = {
        "hourly": {
            "forecast": [
                {
                    "wind": {
                        "speed": 18.0,  # 5.0 m/s
                        "degree": 90.0,
                    }
                }
            ]
        }
    }

    mock_entry = MagicMock()
    mock_entry.entry_id = "test_entry"
    mock_entry.options = {}
    mock_entry.subentries = {"sub_1": mock_subentry}
    mock_entry.runtime_data.edr = mock_edr
    mock_entry.runtime_data.app_coordinators = {"sub_1": mock_app_coord}
    mock_entry.runtime_data.notification_service.set_callback = MagicMock()

    cam = WindParticlesCam(mock_entry)
    cam.hass = MagicMock()
    cam.hass.async_add_executor_job = AsyncMock(
        side_effect=lambda func, *args: func(*args)
    )
    cam._background_image = Image.new("RGBA", (200, 200), (30, 30, 30, 255))
    cam._radar_bbox = (0.0, 6300000, 1000000, 7300000)
    cam.async_ensure_background = AsyncMock()

    img_bytes = await cam.async_camera_image()
    assert img_bytes is not None
    assert img_bytes[:4] == b"GIF8"


@pytest.mark.asyncio
async def test_hybrid_camera_mixes_app_target_wind():
    """Test HybridWeatherCam mixes in App API target observations with radar reflectivity."""
    from custom_components.nl_weather.camera import HybridWeatherCam

    mock_edr = MagicMock()
    mock_edr.get_wind_observations = AsyncMock(return_value=[])

    mock_wms = MagicMock()
    radar_buf = io.BytesIO()
    Image.new("RGBA", (200, 200), (0, 0, 0, 0)).save(radar_buf, format="PNG")
    mock_wms.radar_forecast_image = AsyncMock(return_value=radar_buf)

    mock_subentry = MagicMock()
    mock_subentry.data = {
        "latitude": 52.37,
        "longitude": 4.89,
    }

    mock_app_coord = MagicMock()
    mock_app_coord.data = {
        "wind": {
            "speed": 14.4,  # 4.0 m/s
            "degree": 180.0,
        }
    }

    mock_entry = MagicMock()
    mock_entry.entry_id = "test_entry"
    mock_entry.options = {}
    mock_entry.subentries = {"sub_1": mock_subentry}
    mock_entry.runtime_data.edr = mock_edr
    mock_entry.runtime_data.wms = mock_wms
    mock_entry.runtime_data.app_coordinators = {"sub_1": mock_app_coord}
    mock_entry.runtime_data.notification_service.set_callback = MagicMock()

    cam = HybridWeatherCam(mock_entry)
    cam.hass = MagicMock()
    cam.hass.async_add_executor_job = AsyncMock(
        side_effect=lambda func, *args: func(*args)
    )
    cam._background_image = Image.new("RGBA", (200, 200), (30, 30, 30, 255))
    cam._radar_bbox = (0.0, 6300000, 1000000, 7300000)
    cam.async_ensure_background = AsyncMock()
    cam._latest_radar_datetime = AsyncMock(
        return_value=datetime(2026, 10, 29, 14, 0, tzinfo=timezone.utc)
    )

    img_bytes = await cam.async_camera_image()
    assert img_bytes is not None
    assert img_bytes[:4] == b"GIF8"


def test_decode_wms_wind_speed_color():
    """Test decoding RGB color pixels to wind speed values in m/s."""
    # Near calm: (210, 248, 254) -> ~0.30 m/s
    assert pytest.approx(decode_wms_wind_speed_color(210, 248, 254), abs=0.2) == 0.30
    # Gentle: (97, 221, 171) -> ~2.61 m/s
    assert pytest.approx(decode_wms_wind_speed_color(97, 221, 171), abs=0.2) == 2.61
    # Fresh: (153, 161, 35) -> ~4.86 m/s
    assert pytest.approx(decode_wms_wind_speed_color(153, 161, 35), abs=0.2) == 4.86
    # Strong: (144, 29, 99) -> ~8.92 m/s
    assert pytest.approx(decode_wms_wind_speed_color(144, 29, 99), abs=0.2) == 8.92

    # Scale with max_speed = 35.0
    val_scaled = decode_wms_wind_speed_color(153, 161, 35, max_speed=35.0)
    assert pytest.approx(val_scaled, abs=1.0) == 4.86 * 3.5


def test_decode_app_wind_speed_color():
    """Test decoding RGB pixel via App API dynamic legend steps."""
    legend_steps = [
        {"value": 0, "color": "#262054"},
        {"value": 18, "color": "#1B8A50"},  # 18 km/h = 5.0 m/s
        {"value": 36, "color": "#FFE602"},  # 36 km/h = 10.0 m/s
    ]
    # Exact green match -> 5.0 m/s
    spd = decode_app_wind_speed_color(0x1B, 0x8A, 0x50, legend_steps)
    assert pytest.approx(spd, abs=0.01) == 5.0

    # Yellow match -> 10.0 m/s
    spd_yellow = decode_app_wind_speed_color(0xFF, 0xE6, 0x02, legend_steps)
    assert pytest.approx(spd_yellow, abs=0.01) == 10.0


def test_grid_apply_speed_raster():
    """Test modulating IDW direction vectors with high-resolution speed raster."""
    obs = WindObservation(
        station_id="1",
        lon=4.8,
        lat=52.3,
        x=534335.0,
        y=6854652.0,
        speed=4.0,
        direction=270.0,  # From West -> East (u = 4, v = 0)
        u=4.0,
        v=0.0,
    )
    bbox = (530000.0, 6850000.0, 550000.0, 6880000.0)
    grid = WindVectorGrid([obs], bbox, grid_w=4, grid_h=4)

    assert pytest.approx(grid.u_grid[0][0], abs=0.1) == 4.0
    assert pytest.approx(grid.v_grid[0][0], abs=0.1) == 0.0

    # Create dummy speed raster: half masked, half 8.92 m/s color (144, 29, 99)
    raster = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    # Fill bottom right with strong wind color
    raster.putpixel((3, 3), (144, 29, 99, 255))

    modulated = grid.apply_speed_raster(raster, max_speed=10.0)
    assert modulated == 1

    # Unmasked cell should now have ~8.92 m/s speed while keeping direction (u > 0, v = 0)
    assert pytest.approx(grid.u_grid[3][3], abs=0.3) == 8.92
    assert pytest.approx(grid.v_grid[3][3], abs=0.1) == 0.0

    # Transparent cell should retain original EDR speed (4.0 m/s)
    assert pytest.approx(grid.u_grid[0][0], abs=0.1) == 4.0


@pytest.mark.asyncio
async def test_wind_camera_with_wms_speed_raster():
    """Test WindParticlesCam retrieving and applying WMS wind speed raster."""
    mock_edr = MagicMock()
    mock_edr.get_wind_observations = AsyncMock(
        return_value=[
            {
                "eumetnet:locationId": "06240",
                "domain": {"axes": {"x": {"values": [4.79]}, "y": {"values": [52.31]}}},
                "ranges": {"dd": {"values": [270.0]}, "ff": {"values": [5.0]}},
            }
        ]
    )

    mock_wms = MagicMock()
    # Mock wind speed raster image
    wind_buf = io.BytesIO()
    wind_img = Image.new("RGBA", (200, 200), (108, 212, 140, 255))  # ~3.06 m/s
    wind_img.save(wind_buf, format="PNG")
    mock_wms.wind_speed_image = AsyncMock(return_value=wind_buf)
    mock_wms.get_capabilities_wind = AsyncMock()

    mock_entry = MagicMock()
    mock_entry.entry_id = "test_entry"
    mock_entry.options = {}
    mock_entry.subentries = {}
    mock_entry.runtime_data.edr = mock_edr
    mock_entry.runtime_data.wms = mock_wms
    mock_entry.runtime_data.notification_service.set_callback = MagicMock()

    cam = WindParticlesCam(mock_entry)
    cam.hass = MagicMock()
    cam.hass.async_add_executor_job = AsyncMock(
        side_effect=lambda func, *args: func(*args)
    )
    cam._background_image = Image.new("RGBA", (200, 200), (30, 30, 30, 255))
    cam._radar_bbox = (0.0, 6300000, 1000000, 7300000)
    cam.async_ensure_background = AsyncMock()
    cam._latest_wind_datetime = AsyncMock(
        return_value=datetime(2026, 10, 30, 11, 20, tzinfo=timezone.utc)
    )

    img_bytes = await cam.async_camera_image()
    assert img_bytes is not None
    assert img_bytes[:4] == b"GIF8"
    mock_wms.wind_speed_image.assert_awaited_once()


@pytest.mark.asyncio
async def test_app_windspeed_measurements():
    """Test KNMI App API windspeed_measurements method."""
    from custom_components.nl_weather.KNMI.app import App

    mock_session = MagicMock()
    app = App(mock_session)
    app.get = AsyncMock(
        return_value={"time": "2026-10-30T10:50:00Z", "legend": {"steps": []}}
    )

    data = await app.windspeed_measurements(unit="kilometerPerHour")
    assert "legend" in data
    app.get.assert_awaited_once_with(
        "measurements/windspeed", {"unit": "kilometerPerHour"}
    )
