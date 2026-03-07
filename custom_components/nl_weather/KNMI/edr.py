import json
import logging
from datetime import datetime, timezone

import aiohttp

BASE_URL = "https://api.dataplatform.knmi.nl/edr/v1/collections/10-minute-in-situ-meteorological-observations"
BBOX_NL = "3.3,50.6,7.3,53.5"

_LOGGER = logging.getLogger(__name__)


def _format_dt(dt):
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


class EDR:
    _session: aiohttp.ClientSession

    def __init__(self, aiohttp_session, token):
        self._session = aiohttp_session
        self._token = token

    async def get(self, endpoint: str, params=None):
        headers = {"Authorization": self._token}
        _LOGGER.debug(f"Calling EDR API endpoint {endpoint} with {params}")
        async with self._session.get(
            f"{BASE_URL}{endpoint}", headers=headers, params=params
        ) as resp:
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
        params = {"datetime": dt, "bbox": BBOX_NL}
        return await self.get("/locations", params)

    async def cube(self, params):
        return await self.get("/cube", params)

    async def location(self, location, params):
        return await self.get(f"/locations/{location}", params)

    async def get_cube_coverages(self, dt: datetime, parameters):
        params = {
            "datetime": dt.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "parameter-name": ",".join(parameters),
            "bbox": BBOX_NL,
        }
        coverage_collection = await self.cube(params)

        # Find all coverages with all parameters listed
        coverages = [
            c
            for c in coverage_collection["coverages"]
            if all(p in c["ranges"] for p in parameters)
        ]
        _LOGGER.debug(f"Found {len(coverages)} coverages with all parameters")

        return coverages

    async def get_location_coverage(self, location, dt: datetime, parameters):
        params = {
            "datetime": dt.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "parameter-name": ",".join(parameters),
        }
        coverage_collection = await self.location(location, params)

        return coverage_collection["coverages"][0]

    async def get_latest_datetime(self):
        metadata = await self.metadata()
        return datetime.fromisoformat(metadata["extent"]["temporal"]["interval"][0][1])


class NotFoundError(Exception):
    """Exception class for no result found"""


class TokenInvalid(Exception):
    """Exception class when token is not accepted"""


class ServerError(Exception):
    """Exception class for server error"""


class InvalidRequest(Exception):
    """Exception class for invalid request"""
