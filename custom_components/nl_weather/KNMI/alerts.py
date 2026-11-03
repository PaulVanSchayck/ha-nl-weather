"""Parsing of KNMI nationwide alerts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

# Higher is more severe
LEVEL_SEVERITY = {"yellow": 1, "orange": 2, "red": 3}


@dataclass
class Alert:
    warning_id: str
    weather_type: int
    headline: str
    level: str
    onset: datetime | None
    expires: datetime | None
    # Each polygon is a list of rings of (lon, lat); the first ring is the exterior
    polygons: list[list[list[tuple[float, float]]]]

    @property
    def severity(self) -> int:
        return LEVEL_SEVERITY[self.level]

    def is_active(self, now: datetime) -> bool:
        if self.onset is not None and self.onset > now:
            return False
        return self.expires is None or self.expires > now


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _parse_optional_dt(value: str | None) -> datetime | None:
    return _parse_dt(value) if value else None


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
            if part.get("color") not in LEVEL_SEVERITY:
                continue
            polygons = _polygons(part["area"])
            if polygons:
                alerts.append(
                    Alert(
                        part["id"],
                        warning["weatherType"],
                        warning.get("headline", ""),
                        part["color"],
                        _parse_optional_dt(part.get("onset", warning.get("onset"))),
                        _parse_optional_dt(part.get("expires", warning.get("expires"))),
                        polygons,
                    )
                )
    alerts.sort(key=lambda a: a.severity, reverse=True)
    return alerts
