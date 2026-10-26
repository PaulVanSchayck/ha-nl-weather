"""Tests for NL Weather services definitions."""

from pathlib import Path

import yaml

from custom_components.nl_weather.const import NLWeatherEntityFeature


def test_services_yaml_schema() -> None:
    """Test that services.yaml is valid and configures get_minute_forecast target supported_features."""
    services_path = (
        Path(__file__).parent.parent
        / "custom_components"
        / "nl_weather"
        / "services.yaml"
    )
    with open(services_path, encoding="utf-8") as f:
        services = yaml.safe_load(f)

    assert "get_minute_forecast" in services
    target_entity = services["get_minute_forecast"]["target"]["entity"]
    assert target_entity["domain"] == "weather"
    assert target_entity["integration"] == "nl_weather"
    assert target_entity["supported_features"] == [
        int(NLWeatherEntityFeature.FORECAST_MINUTE)
    ]
    assert target_entity["supported_features"] == [32]
