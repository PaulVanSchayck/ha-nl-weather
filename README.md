# NL Weather

**NL Weather** is a Home Assistant integration that provides weather forecasts, observations, 
precipitation (e.g. rain) radar and warnings in The Netherlands — using public data directly fetched from 
KNMI (the Royal Netherlands Meteorological Institute).

## Features

- Integration as a `weather` provider (compatible with Home Assistant weather-entity standards)
- Can have multiple configurable locations (limited to the Netherlands) with
  - Current weather observations (temperature, humidity, wind, etc.)  
  - Weather forecast (hourly/daily)
  - Weather alerts (issued by KNMI)
- Precipitation / rain radar and forecast (rain intensity, movement, etc.)  
- Optional additional sensors/entities for detailed data (as provided by KNMI)
- Data fetched directly from official KNMI APIs
  - Uses KNMI's MQTT Notification Service to reduce polling

## Installation

### Via HACS (recommended)

1. Ensure you have HACS installed in your Home Assistant.
2. Add this repository as a custom integration (if not already in the default store).  
3. In Home Assistant: go to **Settings → Devices & Services → Add Integration**.  
4. Search for **NL Weather** and install.  
5. Restart Home Assistant if required.  

### Manual Installation

If you prefer manual install (or HACS is not available):

1. Download or clone this repository.  
2. Copy the folder `custom_components/nl_weather` to your Home Assistant `custom_components/` directory.  
3. Restart Home Assistant.  
4. Add the integration via **Settings → Devices & Services → Add Integration → NL Weather** 

> ⚠️ If the integration does not show up after installing via HACS or copying manually — try clearing browser cache, 
> restart Home Assistant again, and verify that the folder structure is correct (i.e. `custom_components/nl_weather/…`).

## Configuration

After adding the integration you'll first need to configure your API keys.

### Step 1. Connect to KNMI Data Platform APIs

You can get API keys from https://developer.dataplatform.knmi.nl/

### Step 2. Configure a weather location 

To start receiving weather observations and forecasts, add a location: 
**Settings → Devices & services → NL Weather → Add location**"


## Entities Created

The integration will add `weather.weer_thuis_observations` and `weather.weer_thuis_forecast`, plus optional sensor 
entities for detailed data such as:

- Temperature, humidity, pressure  
- Wind speed and direction  
- Rain / precipitation intensity / radar data  
- Forecast data (daily / hourly)  
- Warnings / alerts  

This allows you to use the data in automations, dashboards (Lovelace), and scripts just like with any other weather integration.

## Contributing

Contributions, bug reports, feature requests are welcome. Feel free to open an issue or submit a pull request.  

## License

Apache License, Version 2.0 

## Disclaimer / Notes

- Forecast and weather observations provided by Koninklijk Nederlands Meteorologisch Instituut (KNMI) 
licensed under CC-BY 4.0
- Weather data, radar images, forecasts and warnings are provided by KNMI; the integration simply fetches and 
exposes them in Home Assistant.  
 

---

Thank you for using **NL Weather**! If you like it, please consider starring the repo ⭐  

