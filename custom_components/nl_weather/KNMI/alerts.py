"""Validated GeoJSON parsing and location filtering for KNMI nationwide warnings."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from math import isfinite

type Ring = list[tuple[float, float]]
type Polygon = list[Ring]


class AlertLevel(StrEnum):
    """KNMI warning severity in ascending order."""

    NONE = "none"
    YELLOW = "yellow"
    ORANGE = "orange"
    RED = "red"


SEVERITY: dict[AlertLevel, int] = {
    AlertLevel.NONE: 0,
    AlertLevel.YELLOW: 1,
    AlertLevel.ORANGE: 2,
    AlertLevel.RED: 3,
}


def _inside_ring(lon: float, lat: float, ring: Ring) -> bool:
    """Test inclusion using even-odd ray casting, including boundary points."""
    inside = False
    for index, (x1, y1) in enumerate(ring):
        x2, y2 = ring[(index + 1) % len(ring)]
        cross = (lon - x1) * (y2 - y1) - (lat - y1) * (x2 - x1)
        if abs(cross) < 1e-10 and min(x1, x2) <= lon <= max(x1, x2) and min(
            y1, y2
        ) <= lat <= max(y1, y2):
            return True
        if (y1 > lat) != (y2 > lat) and lon < (
            (x2 - x1) * (lat - y1) / (y2 - y1) + x1
        ):
            inside = not inside
    return inside


@dataclass
class Alert:
    """One timed warning part and its geographic coverage."""

    warning_id: str
    weather_type: int
    headline: str
    level: AlertLevel
    onset: datetime
    expires: datetime
    polygons: list[Polygon]
    description: str = ""
    details: str = ""
    _bboxes: list[tuple[float, float, float, float]] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        """Cache exterior bounding boxes for efficient location matching."""
        self._bboxes = []
        for polygon in self.polygons:
            points = polygon[0]
            self._bboxes.append(
                (
                    min(lon for lon, _ in points),
                    min(lat for _, lat in points),
                    max(lon for lon, _ in points),
                    max(lat for _, lat in points),
                )
            )

    @property
    def severity(self) -> int:
        """Return a comparable severity rank."""
        return SEVERITY[self.level]

    def is_active(self, now: datetime) -> bool:
        """Check the half-open warning interval."""
        return self.onset <= now < self.expires

    def contains(self, lat: float, lon: float) -> bool:
        """Check polygon exteriors and exclude any interior holes."""
        for polygon, (min_lon, min_lat, max_lon, max_lat) in zip(
            self.polygons, self._bboxes, strict=True
        ):
            if not (min_lon <= lon <= max_lon and min_lat <= lat <= max_lat):
                continue
            if _inside_ring(lon, lat, polygon[0]) and not any(
                _inside_ring(lon, lat, hole) for hole in polygon[1:]
            ):
                return True
        return False


def get_active_alerts(
    alerts: list[Alert] | None, lat: float, lon: float, now: datetime
) -> list[Alert]:
    """Return active warning parts covering the given location."""
    return [
        alert
        for alert in alerts or []
        if alert.is_active(now) and alert.contains(lat, lon)
    ]


def _parse_datetime(value: object) -> datetime:
    """Parse an aware KNMI ISO-8601 timestamp."""
    if not isinstance(value, str):
        raise ValueError("KNMI warning timestamp is missing or not a string")
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("KNMI warning timestamp must contain a timezone")
    return timestamp


def _parse_polygons(geometry: object) -> list[Polygon]:
    """Validate Polygon/MultiPolygon coordinates from a GeoJSON geometry."""
    if not isinstance(geometry, dict):
        return []
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list):
        return []
    if geometry_type == "Polygon":
        raw_polygons = [coordinates]
    elif geometry_type == "MultiPolygon":
        raw_polygons = coordinates
    else:
        return []

    polygons: list[Polygon] = []
    for raw_polygon in raw_polygons:
        if not isinstance(raw_polygon, list) or not raw_polygon:
            continue
        rings: Polygon = []
        for raw_ring in raw_polygon:
            if not isinstance(raw_ring, list) or len(raw_ring) < 3:
                rings = []
                break
            points: Ring = []
            for raw_point in raw_ring:
                if (
                    not isinstance(raw_point, (list, tuple))
                    or len(raw_point) < 2
                    or not all(
                        isinstance(coordinate, (int, float))
                        and not isinstance(coordinate, bool)
                        and isfinite(coordinate)
                        for coordinate in raw_point[:2]
                    )
                ):
                    points = []
                    break
                lon, lat = raw_point[:2]
                if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                    points = []
                    break
                points.append((float(lon), float(lat)))
            if len(points) < 3:
                rings = []
                break
            rings.append(points)
        if rings:
            polygons.append(rings)
    return polygons


def parse_alerts(snapshot: object) -> list[Alert]:
    """Parse warning parts, ignoring invalid parts and sorting by severity.

    A malformed top-level response is an error rather than an empty warning list.
    """
    if not isinstance(snapshot, dict) or not isinstance(
        snapshot.get("warnings"), list
    ):
        raise ValueError("KNMI nationwide warnings response has no warnings list")

    alerts: list[Alert] = []
    for warning in snapshot["warnings"]:
        if not isinstance(warning, dict):
            continue
        parts = warning.get("parts", [])
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict):
                continue
            polygons = _parse_polygons(part.get("area"))
            if not polygons:
                continue
            try:
                level = AlertLevel(part["color"])
                onset = _parse_datetime(part.get("onset", warning.get("onset")))
                expires = _parse_datetime(part.get("expires", warning.get("expires")))
                weather_type = int(warning["weatherType"])
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if onset >= expires or level == AlertLevel.NONE:
                continue
            alerts.append(
                Alert(
                    warning_id=str(part.get("id", warning.get("id", ""))),
                    weather_type=weather_type,
                    headline=str(warning.get("headline") or ""),
                    level=level,
                    onset=onset,
                    expires=expires,
                    polygons=polygons,
                    description=str(warning.get("description") or ""),
                    details=str(warning.get("detailedDescription") or ""),
                )
            )
    alerts.sort(key=lambda alert: alert.severity, reverse=True)
    return alerts
