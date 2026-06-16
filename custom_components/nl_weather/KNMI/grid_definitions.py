import os
from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import Optional, Dict

from pyproj import Transformer

from .helpers import Coordinate


class GridDefinitions(StrEnum):
    FORECAST = "A"
    RADAR = "B"


class Direction(Enum):
    SWCR = "SWCR"
    NWCR = "NWCR"


@dataclass(frozen=True)
class Steps:
    lat: int
    lon: int


class Grid:
    """
    Compile immutable grid with optional transformer.
    """

    def __init__(
        self,
        sw: Coordinate,
        ne: Coordinate,
        steps: Steps,
        prefix: str,
        proj: str,
        direction: Direction,
    ):
        self.sw = sw
        self.ne = ne
        self.steps = steps
        self.prefix = prefix
        self.direction = direction

        os.environ.setdefault("PROJ_IGNORE_CELESTIAL_BODY", "YES")
        self.transformer = (
            None
            if proj.lower() == "epsg4326"
            else Transformer.from_crs(
                "EPSG:4326",
                self._normalize_proj(proj),
                always_xy=True,
            )
        )

        self.lat_mult = self.steps.lat / (self.ne.lat - self.sw.lat)
        self.lon_mult = self.steps.lon / (self.ne.lon - self.sw.lon)

    @staticmethod
    def _normalize_proj(proj: str) -> str:
        # From:
        # https://gitlab.com/KNMI-OSS/KNMI-App/knmi-app-android/-/blob/main/app/src/main/java/nl/knmi/weer/crs/ProjectionDefinition.kt
        proj = proj.lower()
        if proj == "epsg28992":
            return "EPSG:28992"
        if proj == "radar":
            return "+proj=stere +lat_0=90 +lon_0=0 +lat_ts=60 +a=6378.14 +b=6356.75 +x_0=0 y_0=0"
        return proj

    def _to_grid(self, coord: Coordinate) -> Coordinate:
        if self.transformer is None:
            return coord
        x, y = self.transformer.transform(coord.lon, coord.lat)
        return Coordinate(lat=y, lon=x)

    def contains(self, c: Coordinate) -> bool:
        if self.direction == Direction.SWCR:
            return (
                self.sw.lat <= c.lat < self.ne.lat
                and self.sw.lon <= c.lon < self.ne.lon
            )

        return self.sw.lat < c.lat <= self.ne.lat and self.sw.lon <= c.lon < self.ne.lon

    def cell_number(self, coord_epsg4326: Coordinate) -> Optional[int]:
        c = self._to_grid(coord_epsg4326)

        if not self.contains(c):
            return None

        if self.direction == Direction.SWCR:
            lat_cell = int((c.lat - self.sw.lat) * self.lat_mult)
            lon_cell = int((c.lon - self.sw.lon) * self.lon_mult)
        else:
            lat_cell = int((self.ne.lat - c.lat) * self.lat_mult)
            lon_cell = int((c.lon - self.sw.lon) * self.lon_mult)

        return lat_cell + lon_cell * self.steps.lat

    def cell(self, coord: Coordinate) -> Optional[str]:
        n = self.cell_number(coord)
        return None if n is None else f"{self.prefix}{n}"


class GridManager:
    def __init__(self, grids: Dict[GridDefinitions, Grid]):
        self.grids = grids

    @staticmethod
    def default() -> "GridManager":
        # These grid definitions are from:
        # https://gitlab.com/KNMI-OSS/KNMI-App/knmi-app-android/-/blob/main/app/src/main/java/nl/knmi/weer/network/config/AppRemoteConfigClient.kt
        return GridManager(
            {
                GridDefinitions.FORECAST: Grid(
                    sw=Coordinate(50.7, 3.2),
                    ne=Coordinate(53.6, 7.4),
                    steps=Steps(35, 30),
                    prefix=GridDefinitions.FORECAST.value,
                    proj="epsg4326",
                    direction=Direction.NWCR,
                ),
                GridDefinitions.RADAR: Grid(
                    sw=Coordinate(-4240, 247),
                    ne=Coordinate(-3889, 510),
                    steps=Steps(351, 263),
                    prefix=GridDefinitions.RADAR.value,
                    proj="radar",
                    direction=Direction.NWCR,
                ),
                # Defined in code, but unused currently
                # "C": Grid(
                #     sw=Coordinate(50.755, 3.365),
                #     ne=Coordinate(53.555, 7.225),
                #     steps=Steps(281, 387),
                #     prefix="C",
                #     proj="epsg4326",
                #     direction=Direction.NWCR,
                # ),
            }
        )

    def cell(self, grid_id: GridDefinitions, coord: Coordinate) -> Optional[str]:
        return self.grids[grid_id].cell(coord)
