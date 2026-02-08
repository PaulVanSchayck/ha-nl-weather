from math import radians, sin, cos, atan2, sqrt, log, tan, pi

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

def closest_coverage(coverages, location):
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

def epsg4325_to_epsg3857(lon, lat):
    """Convert lon/lat (deg) to EPSG:3857 meters (x, y)."""
    # clamp latitude to valid Web Mercator range to avoid math domain errors
    lat = max(min(lat, 85.05112878), -85.05112878)
    R = 6378137.0  # EPSG:3857 radius
    x = R * radians(lon)
    y = R * log(tan(pi / 4.0 + radians(lat) / 2.0))
    return x, y