"""Test services configuration schema validation and registration."""

from pathlib import Path

import homeassistant.helpers.service as service_helper
import yaml

from custom_components.nl_weather.const import NLWeatherEntityFeature
from custom_components.nl_weather.weather import SERVICE_GET_MINUTE_FORECAST


def test_services_yaml_schema_validation() -> None:
    """Test that services.yaml conforms to Home Assistant service schema requirements."""
    services_file = Path("custom_components/nl_weather/services.yaml")
    assert services_file.is_file()

    with services_file.open("r", encoding="utf-8") as f:
        services_data = yaml.safe_load(f)

    # Validate against Home Assistant's service schema parser
    validated = service_helper._SERVICES_SCHEMA(services_data)

    assert SERVICE_GET_MINUTE_FORECAST in validated
    target_entity = validated[SERVICE_GET_MINUTE_FORECAST]["target"]["entity"][0]
    assert target_entity["domain"] == ["weather"]
    assert target_entity["integration"] == "nl_weather"
    assert "supported_features" not in target_entity


def test_weather_entity_feature_constant() -> None:
    """Test that NLWeatherEntityFeature.FORECAST_MINUTE constant value is 32."""
    assert NLWeatherEntityFeature.FORECAST_MINUTE == 32
