from math import atan2, cos, log, pi, radians, sin, sqrt, tan


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the Haversine distance between two points on the Earth specified in decimal degrees."""
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c


def sort_coverage_on_distance(coverages, location):
    return sorted(
        coverages,
        key=lambda c: haversine(
            c["domain"]["axes"]["y"]["values"][0],
            c["domain"]["axes"]["x"]["values"][0],
            location["lat"],
            location["lon"],
        ),
    )


def epsg4325_to_epsg3857(lon, lat):
    """Convert lon/lat (deg) to EPSG:3857 meters (x, y)."""
    # clamp latitude to valid Web Mercator range to avoid math domain errors
    lat = max(min(lat, 85.05112878), -85.05112878)
    R = 6378137.0  # EPSG:3857 radius
    x = R * radians(lon)
    y = R * log(tan(pi / 4.0 + radians(lat) / 2.0))
    return x, y
