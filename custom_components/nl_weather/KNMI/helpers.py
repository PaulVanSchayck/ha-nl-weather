"""Helpers for KNMI data processing."""

from math import atan2, cos, log, pi, radians, sin, sqrt, tan
from typing import Final

# Earth radius constants
EARTH_RADIUS_KM: Final = 6371.0  # Haversine formula Earth radius (kilometers)
EARTH_RADIUS_METERS: Final = 6378137.0  # EPSG:3857 Web Mercator radius (meters)
WEB_MERCATOR_MAX_LAT: Final = 85.05112878  # Maximum valid latitude for Web Mercator


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the Haversine distance between two points on the Earth specified in decimal degrees.

    Args:
        lat1: Latitude of first point in decimal degrees.
        lon1: Longitude of first point in decimal degrees.
        lat2: Latitude of second point in decimal degrees.
        lon2: Longitude of second point in decimal degrees.

    Returns:
        Distance between the two points in kilometers.
    """
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return EARTH_RADIUS_KM * c


def closest_coverage(coverages, location):
    """Find the coverage object closest to the given location.

    Args:
        coverages: List of coverage objects with domain axis information.
        location: Dictionary with 'lat' and 'lon' keys for the target location.

    Returns:
        Tuple of (coverage_object, distance_in_km) for the closest coverage.
    """
    coverage, distance = min(
        (
            (
                c,
                haversine(
                    c["domain"]["axes"]["y"]["values"][0],
                    c["domain"]["axes"]["x"]["values"][0],
                    location["lat"],
                    location["lon"],
                ),
            )
            for c in coverages
        ),
        key=lambda x: x[1],
    )
    return coverage, distance


def epsg4325_to_epsg3857(lon: float, lat: float) -> tuple[float, float]:
    """Convert lon/lat (degrees) to EPSG:3857 meters (x, y).

    Args:
        lon: Longitude in decimal degrees.
        lat: Latitude in decimal degrees.

    Returns:
        Tuple of (x, y) coordinates in EPSG:3857 meters (Web Mercator projection).
    """
    # Clamp latitude to valid Web Mercator range to avoid math domain errors
    lat = max(min(lat, WEB_MERCATOR_MAX_LAT), -WEB_MERCATOR_MAX_LAT)
    x = EARTH_RADIUS_METERS * radians(lon)
    y = EARTH_RADIUS_METERS * log(tan(pi / 4.0 + radians(lat) / 2.0))
    return x, y
