"""pytest fixtures for nl_weather tests."""

import sys
from unittest.mock import MagicMock

if "turbojpeg" not in sys.modules:
    sys.modules["turbojpeg"] = MagicMock()

import homeassistant.config_entries as ce
import homeassistant.helpers.entity_platform as ep
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass

if not hasattr(ce, "ConfigSubentry"):
    ce.ConfigSubentry = MagicMock

if not hasattr(ep, "AddConfigEntryEntitiesCallback"):
    ep.AddConfigEntryEntitiesCallback = MagicMock

if not hasattr(SensorDeviceClass, "WIND_DIRECTION"):
    SensorDeviceClass.WIND_DIRECTION = "wind_direction"

if not hasattr(SensorStateClass, "MEASUREMENT_ANGLE"):
    SensorStateClass.MEASUREMENT_ANGLE = "measurement_angle"
