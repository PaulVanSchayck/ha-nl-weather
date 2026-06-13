import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict

from pyproj import Transformer

from .helpers import Coordinate


class Direction(Enum):
    SWCR = "SWCR"
    NWCR = "NWCR"


@dataclass
class Steps:
    latitude: int
    longitude: int


# From:
# https://gitlab.com/KNMI-OSS/KNMI-App/knmi-app-android/-/blob/main/app/src/main/java/nl/knmi/weer/crs/ProjectionDefinition.kt
PROJ_MAP = {
    "epsg4326": "EPSG:4326",
    "epsg28992": "EPSG:28992",
    "radar": "+proj=stere +lat_0=90 +lon_0=0 +lat_ts=60 "
    "+a=6378.14 +b=6356.75 +x_0=0 y_0=0",
}


class ProjectionClient:
    def __init__(self):
        os.environ.setdefault("PROJ_IGNORE_CELESTIAL_BODY", "YES")
        self._transformers = {}

    def transform(self, coord: Coordinate, from_proj: str, to_proj: str) -> Coordinate:
        if from_proj == to_proj:
            return coord

        key = (from_proj, to_proj)
        if key not in self._transformers:
            self._transformers[key] = Transformer.from_crs(
                from_proj, to_proj, always_xy=True
            )

        transformer = self._transformers[key]
        lon, lat = transformer.transform(coord.lon, coord.lat)

        return Coordinate(lat=lat, lon=lon)


class GridDefinition:
    def __init__(
        self,
        south_west: Coordinate,
        north_east: Coordinate,
        steps: Steps,
        prefix: str,
        proj: str,
        direction: Direction,
    ):
        self.south_west = south_west
        self.north_east = north_east
        self.steps = steps
        self.prefix = prefix
        self.proj = PROJ_MAP[proj.lower()]
        self.direction = direction

        self.latitude_multiplier = steps.latitude / (north_east.lat - south_west.lat)
        self.longitude_multiplier = steps.longitude / (north_east.lon - south_west.lon)

        self.projection_client = ProjectionClient()

    def contains(self, coord: Coordinate) -> bool:
        if self.direction == Direction.SWCR:
            return (
                coord.lat >= self.south_west.lat
                and coord.lat < self.north_east.lat
                and coord.lon >= self.south_west.lon
                and coord.lon < self.north_east.lon
            )
        else:  # NWCR
            return (
                coord.lat > self.south_west.lat
                and coord.lat <= self.north_east.lat
                and coord.lon >= self.south_west.lon
                and coord.lon < self.north_east.lon
            )

    def _cell_number(self, coord: Coordinate) -> Optional[int]:
        if not self.contains(coord):
            return None

        if self.direction == Direction.SWCR:
            lat_cell = int((coord.lat - self.south_west.lat) * self.latitude_multiplier)
            lon_cell = int(
                (coord.lon - self.south_west.lon) * self.longitude_multiplier
            )
        else:  # NWCR
            lat_cell = int((self.north_east.lat - coord.lat) * self.latitude_multiplier)
            lon_cell = int(
                (coord.lon - self.south_west.lon) * self.longitude_multiplier
            )

        return lat_cell + lon_cell * self.steps.latitude

    def cell_number(self, coord_epsg4326: Coordinate) -> Optional[int]:
        coord = (
            coord_epsg4326
            if self.proj == "EPSG:4326"
            else self.projection_client.transform(
                coord_epsg4326, "EPSG:4326", self.proj
            )
        )
        return self._cell_number(coord)

    def cell(self, coord_epsg4326: Coordinate) -> Optional[str]:
        num = self.cell_number(coord_epsg4326)
        return f"{self.prefix}{num}" if num is not None else None


class GridManager:
    def __init__(self, grids: Dict[str, GridDefinition]):
        self.grids = grids

    @staticmethod
    def from_defaults() -> "GridManager":
        # These grid definitions are from:
        # https://gitlab.com/KNMI-OSS/KNMI-App/knmi-app-android/-/blob/main/app/src/main/java/nl/knmi/weer/network/config/AppRemoteConfigClient.kt
        return GridManager(
            {
                "A": GridDefinition(
                    Coordinate(50.7, 3.2),
                    Coordinate(53.6, 7.4),
                    Steps(35, 30),
                    "A",
                    "epsg4326",
                    Direction.NWCR,
                ),
                "B": GridDefinition(
                    Coordinate(-4240, 247),
                    Coordinate(-3889, 510),
                    Steps(351, 263),
                    "B",
                    "radar",
                    Direction.NWCR,
                ),
                "C": GridDefinition(
                    Coordinate(50.755, 3.365),
                    Coordinate(53.555, 7.225),
                    Steps(281, 387),
                    "C",
                    "epsg4326",
                    Direction.NWCR,
                ),
            }
        )

    def cell(self, coord: Coordinate, grid_key: str) -> Optional[str]:
        grid = self.grids.get(grid_key)
        if not grid:
            raise ValueError(f"Unknown grid: {grid_key}")
        return grid.cell(coord)

    def cell_all(self, coord: Coordinate) -> Dict[str, Optional[str]]:
        return {key: grid.cell(coord) for key, grid in self.grids.items()}
