import json
import logging
from datetime import datetime, timezone
from math import radians, sin, cos, atan2, sqrt

import aiohttp

BASE_URL = "https://api.dataplatform.knmi.nl/edr/v1/collections/10-minute-in-situ-meteorological-observations"
BBOX_NL = "3.3,50.6,7.3,53.5"

_LOGGER = logging.getLogger(__name__)


def _format_dt(dt):
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")

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
            (c, haversine(
                c["domain"]["axes"]["y"]["values"][0],
                c["domain"]["axes"]["x"]["values"][0],
                location["lat"],
                location["lon"]
            ))
            for c in coverages
        ),
        key=lambda x: x[1]
    )
    return coverage, distance

class EDR:
    _session: aiohttp.ClientSession

    def __init__(self, aiohttp_session, token):
        self._session = aiohttp_session
        self._token = token

    async def get(self, endpoint: str, params=None):
        headers = {"Authorization": self._token}
        _LOGGER.debug(f"Calling EDR API endpoint {endpoint} with {params}")
        async with self._session.get(f"{BASE_URL}{endpoint}", headers=headers, params=params) as resp:
            body = await resp.text()
            try:
                resp.raise_for_status()
            except aiohttp.ClientResponseError as e:
                if e.status == 400:
                    raise InvalidRequest(json.loads(body)) from None
                if e.status == 404:
                    raise NotFoundError("No data found for query") from None
                elif e.status == 403:
                    # TODO: Also handle quota exceeded
                    raise TokenInvalid(json.loads(body)) from None
                elif e.status >= 500:
                    raise ServerError(f"Status code: {e.status}") from None
                raise
            return json.loads(body)

    async def metadata(self):
        return await self.get("")

    async def locations(self):
        # Get current locations
        dt = _format_dt(datetime.now(timezone.utc))
        params = {
            "datetime": dt,
        }
        return await self.get("/locations", params)

    async def cube(self, params):
        return await self.get("/cube", params)

    async def get_coverage(self, dt: datetime, parameters):
        params = {
            "datetime": dt.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "parameter-name": ",".join(parameters),
            "bbox": BBOX_NL,
        }
        coverage_collection = await self.cube(params)

        # Find all coverages with all parameters listed
        coverages = [c for c in coverage_collection['coverages'] if all(p in c["ranges"] for p in parameters)]
        _LOGGER.debug(f"Found {len(coverages)} coverages with all parameters")

        return coverages

    async def get_latest_coverage(self, parameters):
        metadata = await self.metadata()
        latest_dt = datetime.fromisoformat(metadata["extent"]["temporal"]["interval"][0][1])
        return await self.get_coverage(latest_dt, parameters), latest_dt


class NotFoundError(Exception):
    """Exception class for no result found"""

class TokenInvalid(Exception):
    """Exception class when token is not accepted"""

class ServerError(Exception):
    """Exception class for server error"""

class InvalidRequest(Exception):
    """Exception class for invalid request"""
