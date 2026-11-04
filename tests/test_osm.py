"""Tests for how the OSM tile manager responds to map tile provider failures."""

import asyncio
import os
import tempfile
import time

from PIL import Image

from custom_components.nl_weather.const import OSMMapStyle
from custom_components.nl_weather.KNMI.osm import OSMTileManager, _write_file_sync


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
