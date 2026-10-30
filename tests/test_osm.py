"""Tests for OpenStreetMap rendering, zoom calculation, and projection helpers."""

import asyncio
import io
import os
import tempfile
import time

import pytest
from PIL import Image

from custom_components.nl_weather.const import (
    DEFAULT_ZOOM_MARGIN,
    OSMMapStyle,
)
from custom_components.nl_weather.KNMI.helpers import (
    Coordinate,
    epsg3857_to_epsg4326,
    epsg4325_to_epsg3857,
)
from custom_components.nl_weather.KNMI.osm import (
    OSMTileManager,
    calculate_auto_zoom_and_bbox,
    calculate_bbox_for_zoom,
    calculate_weighted_center,
    tile_bounds_3857,
    tile_coordinates,
    transform_standard_osm_tile,
)


def test_epsg_conversions_roundtrip():
    """Test EPSG:4326 to EPSG:3857 and back."""
    original = Coordinate(lat=52.3676, lon=4.9041)  # Amsterdam
    x, y = epsg4325_to_epsg3857(original)
    recovered = epsg3857_to_epsg4326(x, y)

    assert pytest.approx(recovered.lat, abs=1e-5) == original.lat
    assert pytest.approx(recovered.lon, abs=1e-5) == original.lon


def test_tile_coordinates_and_bounds():
    """Test tile coordinates mapping and bounds consistency."""
    coord = Coordinate(lat=52.0907, lon=5.1214)  # Utrecht
    x, y = epsg4325_to_epsg3857(coord)
    zoom = 10

    tx, ty = tile_coordinates(x, y, zoom)
    xmin, ymin, xmax, ymax = tile_bounds_3857(tx, ty, zoom)

    assert xmin <= x <= xmax
    assert ymin <= y <= ymax


def test_calculate_weighted_center():
    """Test weighted center calculation."""
    # Single zone
    zones_single = [(52.0, 5.0, 100.0)]
    center = calculate_weighted_center(zones_single)
    assert center.lat == 52.0
    assert center.lon == 5.0

    # Two equal-weight zones (arithmetic midpoint)
    zones_equal = [
        (52.0, 4.0, 100.0),
        (52.0, 6.0, 100.0),
    ]
    center_eq = calculate_weighted_center(zones_equal)
    assert pytest.approx(center_eq.lat) == 52.0
    assert pytest.approx(center_eq.lon) == 5.0

    # Two unequal-weight zones
    zones_unequal = [
        (50.0, 5.0, 100.0),
        (60.0, 5.0, 300.0),
    ]
    # Weight total = 400. Lat = (50*100 + 60*300) / 400 = (5000 + 18000)/400 = 23000/400 = 57.5
    center_uneq = calculate_weighted_center(zones_unequal)
    assert pytest.approx(center_uneq.lat) == 57.5
    assert pytest.approx(center_uneq.lon) == 5.0


def test_calculate_auto_zoom_and_bbox_single_zone():
    """Test auto zoom calculation for a single zone with 50% margin and min span."""
    zones = [(52.3676, 4.9041, 100.0)]
    center = Coordinate(lat=52.3676, lon=4.9041)

    zoom, bbox = calculate_auto_zoom_and_bbox(
        zones, center, image_size=(1024, 1024), padding=0.50, min_span_meters=25000.0
    )

    # For a 25km min span, zoom should be around 11
    assert 10 <= zoom <= 12
    xmin, ymin, xmax, ymax = bbox
    cx, cy = epsg4325_to_epsg3857(center)
    assert pytest.approx((xmin + xmax) / 2.0, abs=1e-2) == cx
    assert pytest.approx((ymin + ymax) / 2.0, abs=1e-2) == cy


def test_calculate_auto_zoom_and_bbox_nationwide():
    """Test auto zoom calculation for nationwide zones spanning across the Netherlands."""
    zones = [
        (53.2194, 6.5665, 100.0),  # Groningen (North)
        (50.8514, 5.6910, 100.0),  # Maastricht (South)
    ]
    center = calculate_weighted_center(zones)

    zoom, bbox = calculate_auto_zoom_and_bbox(
        zones, center, image_size=(1024, 1024), padding=DEFAULT_ZOOM_MARGIN
    )

    # For ~260km span + 50% margin, zoom should fit the whole country (around 7 or 8)
    assert 6 <= zoom <= 8
    xmin, ymin, xmax, ymax = bbox
    cx, cy = epsg4325_to_epsg3857(center)
    assert pytest.approx((xmin + xmax) / 2.0, abs=1e-2) == cx
    assert pytest.approx((ymin + ymax) / 2.0, abs=1e-2) == cy


def test_calculate_bbox_for_zoom():
    """Test fixed zoom bounding box calculation."""
    center = Coordinate(lat=52.1326, lon=5.2913)
    bbox = calculate_bbox_for_zoom(center, zoom=10, image_size=(1024, 1024))

    xmin, ymin, xmax, ymax = bbox
    cx, cy = epsg4325_to_epsg3857(center)
    assert pytest.approx((xmin + xmax) / 2.0, abs=1e-2) == cx
    assert pytest.approx((ymin + ymax) / 2.0, abs=1e-2) == cy
    assert xmax > xmin
    assert ymax > ymin


def test_transform_standard_osm_tile():
    """Test standard OSM tile transformation for light and dark modes."""
    # Create test tile with distinct colors
    tile = Image.new("RGB", (256, 256), (200, 220, 240))  # Light blue

    # Light transformation: desaturates and slightly softens
    light_tile = transform_standard_osm_tile(tile, dark=False)
    assert light_tile.size == (256, 256)
    r, _g, b = light_tile.getpixel((10, 10))
    # Colors should be closer together (desaturated)
    assert abs(r - b) < 15

    # Dark transformation: inverts and darkens
    dark_tile = transform_standard_osm_tile(tile, dark=True)
    assert dark_tile.size == (256, 256)
    dr, dg, db = dark_tile.getpixel((10, 10))
    # Dark tile pixels should be dark (< 60)
    assert dr < 60 and dg < 60 and db < 60


def test_stitch_and_crop():
    """Test stitching tiles and cropping to exact dimensions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a mock session (not used for this sync method)
        manager = OSMTileManager(session=None, cache_dir=tmpdir)

        center = Coordinate(lat=52.3676, lon=4.9041)
        zoom = 10
        size = (512, 512)
        bbox = calculate_bbox_for_zoom(center, zoom, image_size=size)

        xmin, ymin, xmax, ymax = bbox
        txmin, tymax = tile_coordinates(xmin, ymin, zoom)
        txmax, tymin = tile_coordinates(xmax, ymax, zoom)

        # Generate synthetic tile data
        tiles_data = {}
        for tx in range(txmin, txmax + 1):
            for ty in range(tymin, tymax + 1):
                img = Image.new(
                    "RGB", (256, 256), ((tx * 40) % 255, (ty * 40) % 255, 100)
                )
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                tiles_data[(tx, ty)] = buf.getvalue()

        result = manager._stitch_and_crop(
            tiles_data,
            txmin,
            txmax,
            tymin,
            tymax,
            bbox,
            size,
            zoom,
            OSMMapStyle.MINIMALIST,
            dark=False,
        )

        assert result.size == size
        assert result.mode == "RGBA"


def test_get_known_zones():
    """Test get_known_zones extracts from HA zones and config subentries."""
    from custom_components.nl_weather.KNMI.osm import get_known_zones

    class MockState:
        def __init__(self, attributes):
            self.attributes = attributes

    class MockStates:
        def __init__(self, states):
            self._states = states

        def async_all(self, domain):
            if domain == "zone":
                return self._states
            return []

    class MockConfig:
        latitude = 52.1
        longitude = 5.2

    class MockHass:
        def __init__(self, states):
            self.states = MockStates(states)
            self.config = MockConfig()

    class MockSubentry:
        def __init__(self, data):
            self.data = data

    class MockConfigEntry:
        def __init__(self, subentries):
            self.subentries = subentries

    states = [
        MockState({"latitude": 52.3676, "longitude": 4.9041, "radius": 250.0}),
        MockState({"latitude": 52.0907, "longitude": 5.1214, "radius": 50.0}),
    ]
    subentries = {
        "sub1": MockSubentry({"latitude": 51.9244, "longitude": 4.4777}),
    }

    hass = MockHass(states)
    config_entry = MockConfigEntry(subentries)

    zones = get_known_zones(hass, config_entry)
    assert len(zones) == 3
    # Check radii: 250 stays 250, 50 clamped to min 100, subentry defaults to 100
    assert (52.3676, 4.9041, 250.0) in zones
    assert (52.0907, 5.1214, 100.0) in zones
    assert (51.9244, 4.4777, 100.0) in zones


def test_carto_api_key_cache_path():
    """Test that carto_api_key changes cache path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = OSMTileManager(None, tmpdir)
        bbox = (100.0, 200.0, 300.0, 400.0)
        size = (765, 765)

        path_no_key = mgr._get_background_cache_path(
            bbox, size, 10, "minimalist", False, carto_api_key=None
        )
        path_with_key1 = mgr._get_background_cache_path(
            bbox, size, 10, "minimalist", False, carto_api_key="key1"
        )
        path_with_key2 = mgr._get_background_cache_path(
            bbox, size, 10, "minimalist", False, carto_api_key="key2"
        )

        assert path_no_key != path_with_key1
        assert path_with_key1 != path_with_key2


def test_osm_background_cache_ttl_and_fallback_on_failure():
    """Test that OSM background is cached for a week and keeps old cache if new fetch fails."""

    async def run_test():
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = OSMTileManager(None, tmpdir)
            bbox = (100.0, 200.0, 300.0, 400.0)
            size = (100, 100)
            zoom = 10

            # 1. Pre-populate a fake cached background
            bg_cache_path = mgr._get_background_cache_path(
                bbox, size, zoom, OSMMapStyle.STANDARD.value, False
            )
            fake_img = Image.new("RGBA", size, (123, 45, 67, 255))
            fake_img.save(bg_cache_path, "PNG")

            now = time.time()
            one_day_ago = now - 86400
            os.utime(bg_cache_path, (one_day_ago, one_day_ago))

            class MockHass:
                async def async_add_executor_job(self, fn, *args):
                    return fn(*args)

            hass = MockHass()

            # Should return cached background without touching network
            img_fresh = await mgr.async_get_osm_background(
                hass, bbox, size, zoom, OSMMapStyle.STANDARD, False
            )
            assert img_fresh.getpixel((0, 0)) == (123, 45, 67, 255)

            # 2. Set mtime to 8 days ago (expired TTL > 7 days)
            eight_days_ago = now - (8 * 86400)
            os.utime(bg_cache_path, (eight_days_ago, eight_days_ago))

            # Session is None, so network fetching will fail.
            # The manager MUST catch the failure, preserve the existing cached background, and return it.
            img_fallback = await mgr.async_get_osm_background(
                hass, bbox, size, zoom, OSMMapStyle.STANDARD, False
            )
            assert img_fallback.getpixel((0, 0)) == (123, 45, 67, 255)

            # Verify that mtime was touched/updated so it doesn't fail continuously
            new_mtime = os.path.getmtime(bg_cache_path)
            assert new_mtime > eight_days_ago

    asyncio.run(run_test())


def test_osm_tile_cache_ttl_and_fallback_on_failure():
    """Test that OSM tile is cached for a week and keeps old tile on fetch failure."""

    from custom_components.nl_weather.KNMI.osm import _write_file_sync

    async def run_test():
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = OSMTileManager(None, tmpdir)
            tile_path = mgr._get_tile_cache_path("standard", 10, 500, 500)
            tile_data = b"FAKETILEDATA"
            _write_file_sync(tile_path, tile_data)

            now = time.time()
            # 1. Fresh tile (1 day old)
            one_day_ago = now - 86400
            os.utime(tile_path, (one_day_ago, one_day_ago))
            res = await mgr._fetch_tile("https://dummy.url/tile.png", tile_path)
            assert res == tile_data

            # 2. Expired tile (8 days old) + network failure (session is None)
            eight_days_ago = now - (8 * 86400)
            os.utime(tile_path, (eight_days_ago, eight_days_ago))
            res_fallback = await mgr._fetch_tile(
                "https://dummy.url/tile.png", tile_path
            )
            assert res_fallback == tile_data
            assert os.path.getmtime(tile_path) > eight_days_ago

    asyncio.run(run_test())
