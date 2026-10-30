"""Test services configuration schema validation and registration."""

from pathlib import Path

import homeassistant.helpers.service as service_helper
import yaml

from custom_components.nl_weather.const import NLWeatherEntityFeature
from custom_components.nl_weather.weather import (
    SERVICE_GET_MINUTE_FORECAST,
    NLWeatherCombined,
    NLWeatherForecast,
    NLWeatherObservations,
)


def test_services_yaml_schema_validation() -> None:
    """Test that services.yaml conforms to Home Assistant service schema requirements."""
    services_file = (
        Path(__file__).resolve().parents[1]
        / "custom_components/nl_weather/services.yaml"
    )
    assert services_file.is_file()

    with services_file.open("r", encoding="utf-8") as f:
        services_data = yaml.safe_load(f)

    # Validate against Home Assistant's service schema parser
    validated = service_helper._SERVICES_SCHEMA(services_data)

    assert SERVICE_GET_MINUTE_FORECAST in validated
    target_entity = validated[SERVICE_GET_MINUTE_FORECAST]["target"]["entity"][0]
    assert target_entity["domain"] == ["weather"]
    assert target_entity["integration"] == "nl_weather"
    assert target_entity["supported_features"] == [
        NLWeatherEntityFeature.FORECAST_MINUTE
    ]

    feature = target_entity["supported_features"][0]
    assert NLWeatherForecast.__new__(NLWeatherForecast).supported_features & feature
    assert NLWeatherCombined.__new__(NLWeatherCombined).supported_features & feature
    assert (
        not (
            NLWeatherObservations.__new__(NLWeatherObservations).supported_features or 0
        )
        & feature
    )


def test_weather_entity_feature_constant() -> None:
    """Test that NLWeatherEntityFeature.FORECAST_MINUTE constant value is 32."""
    assert NLWeatherEntityFeature.FORECAST_MINUTE == 32
