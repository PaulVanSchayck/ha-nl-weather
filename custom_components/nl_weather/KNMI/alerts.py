"""Parsing of KNMI nationwide alerts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from itertools import pairwise
from typing import Any


class AlertLevel(StrEnum):
    NONE = "none"
    YELLOW = "yellow"
    ORANGE = "orange"
    RED = "red"


@dataclass
class Alert:
    warning_id: str
    weather_type: int
    headline: str
    level: AlertLevel
    onset: datetime | None
    expires: datetime | None
    # Each polygon is a list of rings of (lon, lat); the first ring is the exterior
    polygons: list[list[list[tuple[float, float]]]]
    description: str = ""
    _bboxes: list[tuple[float, float, float, float]] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        self._bboxes = [_ring_bbox(polygon[0]) for polygon in self.polygons]

    def contains(self, lat: float, lon: float) -> bool:
        """Whether the point lies in the warning area (holes are ignored)."""
        return any(
            _point_in_bbox(lon, lat, bbox) and _point_in_ring(lon, lat, polygon[0])
            for bbox, polygon in zip(self._bboxes, self.polygons, strict=True)
        )

    @property
    def severity(self) -> int:
        return list(AlertLevel).index(self.level)

    def is_active(self, now: datetime) -> bool:
        if self.onset is not None and self.onset > now:
            return False
        return self.expires is None or self.expires > now


def _ring_bbox(ring: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [x for x, _ in ring]
    ys = [y for _, y in ring]
    return min(xs), min(ys), max(xs), max(ys)


def _point_in_bbox(px: float, py: float, bbox: tuple[float, float, float, float]):
    return bbox[0] <= px <= bbox[2] and bbox[1] <= py <= bbox[3]


def _point_in_ring(px: float, py: float, ring: list[tuple[float, float]]) -> bool:
    """Even-odd ray casting."""
    inside = False
    for (x1, y1), (x2, y2) in pairwise(ring):
        if (y1 > py) != (y2 > py) and px < (x2 - x1) * (py - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def get_active_alerts(
    alerts: list[Alert] | None, lat: float, lon: float, now: datetime
) -> list[Alert]:
    """Alerts active now that cover the location, keeping the input order."""
    return [a for a in alerts or [] if a.is_active(now) and a.contains(lat, lon)]


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _polygons(geometry: dict[str, Any]) -> list[list[list[tuple[float, float]]]]:
    if geometry["type"] == "Polygon":
        raw = [geometry["coordinates"]]
    elif geometry["type"] == "MultiPolygon":
        raw = geometry["coordinates"]
    else:
        return []
    return [[[(p[0], p[1]) for p in ring] for ring in poly] for poly in raw]


def parse_alerts(snapshot: dict[str, Any]) -> list[Alert]:
    """Return all warning parts, most severe first. Use Alert.is_active to filter.

    The snapshot is {"warnings": [...]}. Each warning has parts with their own
    color, time window and area.
    """
    alerts: list[Alert] = []
    for warning in snapshot["warnings"]:
        for part in warning.get("parts", []):
            polygons = _polygons(part["area"])
            if polygons:
                alerts.append(
                    Alert(
                        part["id"],
                        warning["weatherType"],
                        warning.get("headline", ""),
                        AlertLevel(part.get("color")),
                        _parse_dt(part.get("onset", warning.get("onset"))),
                        _parse_dt(part.get("expires", warning.get("expires"))),
                        polygons,
                        warning.get("description", ""),
                    )
                )
    alerts.sort(key=lambda a: a.severity, reverse=True)
    return alerts
