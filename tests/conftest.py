"""pytest fixtures for nl_weather tests."""

from unittest.mock import MagicMock
import homeassistant.config_entries as ce
import homeassistant.helpers.entity_platform as ep

if not hasattr(ce, "ConfigSubentry"):
    ce.ConfigSubentry = MagicMock

if not hasattr(ep, "AddConfigEntryEntitiesCallback"):
    ep.AddConfigEntryEntitiesCallback = MagicMock
