import json
import os

import aiohttp
import logging
from math import radians, sin, cos, atan2, sqrt

BASE_URL = "https://api.app.knmi.cloud"
AREA_DEFINITION_PATH = os.path.join(os.path.dirname(__file__), "area_definition-nl_30x35_v2-1.json")

_LOGGER = logging.getLogger(__name__)

# TODO: Get this from one utils directory
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

class App:
    _session: aiohttp.ClientSession
    _area_definition = None

    def __init__(self, aiohttp_session):
        self._session = aiohttp_session

    async def get(self, endpoint: str, params=None):
        _LOGGER.debug(f"Calling KNMI App API endpoint {endpoint} with {params}")
        async with self._session.get(f"{BASE_URL}/{endpoint}", params=params) as resp:
            body = await resp.text()
            try:
                resp.raise_for_status()
            except aiohttp.ClientResponseError as e:
                if e.status == 400:
                    raise InvalidRequest(json.loads(body)) from None
                if e.status == 404:
                    raise NotFoundError("No data found for query") from None
                elif e.status >= 500:
                    raise ServerError(f"Status code: {e.status}: {body}") from None
                raise
            return json.loads(body)

    def load_area_definition(self):
        with open(AREA_DEFINITION_PATH, 'r') as f:
            self._area_definition = json.load(f)

    def get_closest_location(self, location):
        return min(
            self._area_definition["features"],
            key=lambda f: haversine(
                # This gets the center of each polygon (each polygon defines a square box)
                (f["geometry"]["coordinates"][0][0][1] + f["geometry"]["coordinates"][0][2][1]) / 2,
                (f["geometry"]["coordinates"][0][0][0] + f["geometry"]["coordinates"][0][1][0]) / 2,
                location["lat"],
                location["lon"]
            )
        )['properties']['id']

    async def weather(self, location, region):
        params = {
            'location': location,
            'region': region
        }
        return await self.get('weather', params)


class NotFoundError(Exception):
    """Exception class for no result found"""

class TokenInvalid(Exception):
    """Exception class when token is not accepted"""

class ServerError(Exception):
    """Exception class for server error"""

class InvalidRequest(Exception):
    """Exception class for invalid request"""