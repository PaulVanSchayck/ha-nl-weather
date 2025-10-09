"""Constants for the NL Weather integration."""
from datetime import timedelta
from typing import Final

from homeassistant.components.weather import (
    ATTR_CONDITION_CLEAR_NIGHT,
    ATTR_CONDITION_CLOUDY,
    ATTR_CONDITION_EXCEPTIONAL,
    ATTR_CONDITION_FOG,
    ATTR_CONDITION_HAIL,
    ATTR_CONDITION_LIGHTNING,
    ATTR_CONDITION_LIGHTNING_RAINY,
    ATTR_CONDITION_PARTLYCLOUDY,
    ATTR_CONDITION_POURING,
    ATTR_CONDITION_RAINY,
    ATTR_CONDITION_SNOWY,
    ATTR_CONDITION_SNOWY_RAINY,
    ATTR_CONDITION_SUNNY,
    ATTR_CONDITION_WINDY,
    ATTR_CONDITION_WINDY_VARIANT, ATTR_WEATHER_HUMIDITY, ATTR_WEATHER_DEW_POINT, ATTR_WEATHER_PRESSURE,
    ATTR_WEATHER_TEMPERATURE, ATTR_WEATHER_VISIBILITY, ATTR_WEATHER_WIND_BEARING, ATTR_WEATHER_WIND_GUST_SPEED,
    ATTR_WEATHER_WIND_SPEED, ATTR_WEATHER_CLOUD_COVERAGE,
)

DOMAIN = "nl_weather"

CONF_EDR_API_TOKEN: Final = "edr_api_token"
CONF_WMS_TOKEN: Final = "wms_token"
CONF_MQTT_TOKEN: Final = "mqtt_token"

CONDITION_CLASSES: dict[str, list[int]] = {
    ATTR_CONDITION_CLOUDY: [1, 2, 3, 10],
    ATTR_CONDITION_FOG: [20, 30, 32, 33, 34, 35], # TODO: Consider visibility range?
    ATTR_CONDITION_HAIL: [21, 22, 89],
    ATTR_CONDITION_LIGHTNING: [12, 90, 91, 94, ],
    ATTR_CONDITION_LIGHTNING_RAINY: [26, 92, 93, 95, 96],
    ATTR_CONDITION_POURING: [18, 42, 63, 66, 83, 84],
    ATTR_CONDITION_RAINY: [21, 22, 23, 40, 41, 50, 50.5, 51, 52, 53, 54, 55, 56, 57, 58, 60, 60.5, 61, 62, 64, 65,
                           80, 81, 82, 84],
    ATTR_CONDITION_SNOWY: [24, 70, 70.5, 71, 72, 73, 74, 75, 76, 77, 78, 85, 86, 87],
    ATTR_CONDITION_SNOWY_RAINY: [25, 67, 68],
    ATTR_CONDITION_SUNNY: [0],
    ATTR_CONDITION_WINDY: [], # TODO: Take wind in account
    ATTR_CONDITION_WINDY_VARIANT: [],
    ATTR_CONDITION_EXCEPTIONAL: [4,5],
}
CONDITION_MAP = {
    cond_code: cond_ha
    for cond_ha, cond_codes in CONDITION_CLASSES.items()
    for cond_code in cond_codes
}

ATTR_WEATHER_CONDITION = "condition"

PARAMETER_ATTRIBUTE_MAP = {
    ATTR_WEATHER_HUMIDITY : 'rh',
    ATTR_WEATHER_DEW_POINT: 'td',
    ATTR_WEATHER_PRESSURE: 'pp',
    ATTR_WEATHER_TEMPERATURE: 'ta',
    ATTR_WEATHER_VISIBILITY: 'vv',
    ATTR_WEATHER_WIND_BEARING: 'dd',
    ATTR_WEATHER_WIND_GUST_SPEED: 'gff',
    ATTR_WEATHER_WIND_SPEED: 'ff',
    ATTR_WEATHER_CLOUD_COVERAGE: 'n1',
    ATTR_WEATHER_CONDITION: 'ww'

}

# Based on https://gitlab.com/KNMI-OSS/KNMI-App/knmi-app-android/-/blob/main/app/src/main/assets/alert_regions_simplified.geojson
ALERT_REGIONS = {
    "1": 'Drenthe',
    "2": 'Flevoland',
    "3": 'Friesland',
    "4": 'Gelderland',
    "5": 'Groningen',
    "6": 'IJsselmeergebied',
    "7": 'Limburg',
    "8": 'Noord-Brabant',
    "9": 'Noord-Holland',
    "10": 'Overijssel',
    "11": 'Utrecht',
    "12": 'Waddeneilanden',
    "13": 'Waddenzee', # TODO: GeoJSON says IJsselmeer
    "14": 'Zeeland',
    "15": 'Zuid-Holland'
}

APP_API_SCAN_INTERVAL = timedelta(minutes=15)

# Only fetch from EDR for same station if below this value in kilometers
EDR_STATION_MINIMAL_DISTANCE = 50

# Based on https://gitlab.com/KNMI-OSS/KNMI-App/knmi-app-api/-/blob/main/app/helpers/weather.ts
# And https://gitlab.com/KNMI-OSS/KNMI-App/knmi-app-android/-/blob/main/app/src/main/java/nl/knmi/weer/util/WeatherTypeExtension.kt
# 1364-1371 are warning conditions
CONDITION_FORECAST_CLASSES = {
    ATTR_CONDITION_PARTLYCLOUDY: [1380, 1381, 1375, 1387, 1388],
    ATTR_CONDITION_CLOUDY: [1386, 1374],
    ATTR_CONDITION_FOG: [1420, 1421, 1422, 1370],
    ATTR_CONDITION_HAIL: [1416, 1417, 1418],
    ATTR_CONDITION_LIGHTNING: [1368, 1448],
    ATTR_CONDITION_LIGHTNING_RAINY: [1389, 1390, 1391, 1392, 1393, 1394, 1395, 1396, 1397],
    ATTR_CONDITION_POURING: [1379, 1384, 1385, 1366, 1371],
    ATTR_CONDITION_RAINY: [1377, 1382, 1383, 1378],
    ATTR_CONDITION_SNOWY: [1398, 1399, 1401, 1402, 1405, 1406, 1407, 1408, 1409, 1410, 1411, 1412, 1367],
    ATTR_CONDITION_SNOWY_RAINY: [1413, 1414, 1415, 1419, 1364],
    ATTR_CONDITION_SUNNY: [1372, 1365],
    ATTR_CONDITION_CLEAR_NIGHT: [1373, 1376],
    ATTR_CONDITION_WINDY: [1423,1424, 1425],
    ATTR_CONDITION_WINDY_VARIANT: [1369],
    ATTR_CONDITION_EXCEPTIONAL: [],
}
CONDITION_FORECAST_MAP = {
    cond_code: cond_ha
    for cond_ha, cond_codes in CONDITION_FORECAST_CLASSES.items()
    for cond_code in cond_codes
}