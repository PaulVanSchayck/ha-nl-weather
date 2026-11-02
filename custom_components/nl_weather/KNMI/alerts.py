"""Parsing of KNMI local warnings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

# Higher is more severe
LEVEL_SEVERITY = {"yellow": 1, "orange": 2, "red": 3}


@dataclass
class Alert:
    event_id: str
    phenomenon: str
    level: str
    # Each polygon is a list of rings of (lon, lat); the first ring is the exterior
    polygons: list[list[list[tuple[float, float]]]]

    @property
    def severity(self) -> int:
        return LEVEL_SEVERITY[self.level]


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _is_active(window: dict[str, str] | None, now: datetime) -> bool:
    if not window:
        return True
    if "onset" in window and _parse_dt(window["onset"]) > now:
        return False
    return not ("expires" in window and _parse_dt(window["expires"]) <= now)


def _polygons(geometry: dict[str, Any]) -> list[list[list[tuple[float, float]]]]:
    if geometry["type"] == "Polygon":
        raw = [geometry["coordinates"]]
    elif geometry["type"] == "MultiPolygon":
        raw = geometry["coordinates"]
    else:
        return []
    return [[[(p[0], p[1]) for p in ring] for ring in poly] for poly in raw]


def parse_alerts(snapshot: dict[str, Any], now: datetime) -> list[Alert]:
    """Return currently active alert areas, most severe first."""
    alerts: list[Alert] = []
    for event in snapshot.get("events", []):
        if event.get("status") != "actual" or event.get("phenomenon") == "test":
            continue
        for area in event.get("areas", []):
            if area.get("level") not in LEVEL_SEVERITY:
                continue
            if not _is_active(area.get("timeWindow") or event.get("timeWindow"), now):
                continue
            polygons = _polygons(area["geometry"])
            if polygons:
                alerts.append(
                    Alert(
                        event["eventId"], event["phenomenon"], area["level"], polygons
                    )
                )
    alerts.sort(key=lambda a: a.severity, reverse=True)
    return alerts
