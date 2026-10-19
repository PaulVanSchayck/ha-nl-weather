# NL Weather: Home Assistant Development Guide

Use this guide with [AGENTS.md](AGENTS.md) and [AI_POLICY.md](AI_POLICY.md). It documents the repository's current implementation and CI targets; verify the source and workflows when they change.

## Integration architecture

- **Domain:** `nl_weather`; manifest version observed: `0.13.0`.
- **Platforms:** `weather`, `camera`, `sensor`, and `binary_sensor`.
- **Data sources:** KNMI App API, EDR API, WMS, and the KNMI MQTT Notification Service.
- **Configuration:** a config flow validates EDR, WMS, and MQTT credentials and supports multiple location subentries. Locations store coordinates, alert region, and automatic/manual station mode.
- **Setup:** `__init__.py` creates KNMI clients using Home Assistant's shared aiohttp session, stores clients and coordinator maps in the typed `RuntimeData` on `entry.runtime_data`, creates per-location coordinators, performs first refreshes for forecast and EDR coordinators, starts nowcast refresh separately, and forwards the platforms.
- **Coordinators:** `coordinator.py` defines forecast, precipitation-nowcast, and event-driven EDR coordinators plus their data types. They fetch and normalize API data for entities.
- **API clients:** `KNMI/app.py`, `edr.py`, and `wms.py` contain HTTP-facing clients. `KNMI/notification_service.py` implements MQTT notifications used for observation updates.
- **Lifecycle:** options changes reload the entry; `async_migrate_entry` migrates older minor config-entry versions and rejects entries from a future major version. Inspect `__init__.py` and notification-service task ownership before changing setup/unload behavior.

## Lifecycle, networking, and errors

- Reuse `async_get_clientsession(hass)`; do not create or close a session owned by Home Assistant.
- Keep network I/O asynchronous and bounded by the existing client timeout/error-handling design. Do not introduce blocking I/O on the event loop.
- For setup, reload, and unload changes, trace coordinator tasks, MQTT background tasks, subscriptions, and resources. Preserve cancellation semantics and ensure integration-owned resources are stopped correctly.
- Preserve the current distinction between forecast/EDR first-refresh failures and best-effort nowcast refresh unless a task explicitly changes it with regression tests.
- Convert expected coordinator/API failures to the appropriate Home Assistant error, such as `UpdateFailed`, while preserving the original exception with `from err`. Do not turn malformed or failed API data into plausible-looking measurements.
- Treat API responses as untrusted data. Validate shape and types before indexing, converting, or iterating over values.

## Entities and identity

- Platform setup iterates location subentries and associates entities with the corresponding `config_subentry_id`.
- Sensor descriptions centralize translation keys, units, device/state classes, and value functions. Preserve the existing description-driven pattern when extending sensors.
- Entity unique IDs and device identifiers include config-entry/subentry identity and stable keys. Changing them can create duplicate registry entries; preserve them unless a deliberate migration is justified.
- Keep names, translation keys, units, device classes, state classes, enum values, and measurement semantics consistent. Return unavailable values as `None` where appropriate rather than inventing a default.
- Preserve diagnostic classification for observation attributes. Inspect `weather.py` before changing forecast mapping or precipitation-nowcast service behavior; radar rendering is in `camera.py`.

## Python and Home Assistant compatibility

- Test and lint workflows use **Python 3.13**. Root `requirements.txt` targets `homeassistant~=2025.8.0`; this describes the configured test environment, not necessarily the integration's declared minimum or maximum supported Home Assistant release.
- The manifest declares runtime requirements `aiomqtt>=2.5.1` and `pyproj>=3.8.0`. The root requirements file separately lists Home Assistant, `aiomqtt~=2.5.1`, and pinned Ruff. Do not duplicate these lists in `pyproject.toml`.
- Source code uses Python 3.12+ syntax, including PEP 695 type aliases. Keep syntax compatible with the Python version exercised by CI; do not claim broader compatibility without evidence.
- Prefer Home Assistant APIs already used in the integration. Verify version-sensitive or deprecated APIs against the targeted Home Assistant release before changing them.
- Use timezone-aware datetimes and preserve the KNMI timestamp semantics. The coordinator compares hourly forecast timestamps against the current UTC hour; avoid naive/aware comparisons.
- Keep types aligned with the API payloads and existing `TypedDict`/type aliases in `coordinator.py`. Use narrow types and explicit checks rather than broad exception handling.
- Use module-level loggers and contextual messages. Never log tokens, credentials, personal data, or sensitive API payloads. Avoid complete request/response dumps.

## Translations and configuration

- User-facing entity and config-flow translations are in `custom_components/nl_weather/translations/en.json` and `nl.json`. Update both when adding or changing keys or user-visible text.
- Keep translation keys aligned with entity-description `translation_key` values and config-flow/options references. Validate both JSON files after edits. No dedicated translation-alignment test was found in `tests/`.
- Keep credential validation and error mapping in the config flow. Never include credentials in logs, exceptions, or form errors.
- Changes to stored configuration, station modes, or entry versions require migration analysis and focused tests.

## Tests and repository checks

Tests live in `tests/` and use pytest with `pytest-homeassistant-custom-component`; shared fixtures are in `tests/conftest.py`. Existing tests include sensor helper and binary-sensor alert behavior. Config-flow, coordinator, API-client, and lifecycle changes should add focused coverage where relevant. Keep ordinary tests deterministic and offline; do not require live KNMI credentials.

### Commands used by CI

Run from the repository root:

```bash
# Same test invocation as CI
PYTHONPATH=. pytest

# Dependency consistency check from the test workflow
python -m pip check

# Ruff checks from the lint workflow
python3 -m ruff check .
python3 -m ruff format . --check

# JSON syntax checks, useful after editing these files
python -m json.tool custom_components/nl_weather/translations/en.json
python -m json.tool custom_components/nl_weather/translations/nl.json
python -m json.tool custom_components/nl_weather/manifest.json
```

The test workflow installs `requirements.txt` plus `pyproj`, `pytest`, `pytest-homeassistant-custom-component`, and `pycares<5`, then runs `pip check` and pytest. The `pycares<5` constraint is specific to that workflow's environment; do not move it into the runtime manifest without separate justification.

The lint workflow installs the pinned Ruff version from `requirements.txt` and runs the two Ruff commands above. The validation workflow runs Home Assistant **hassfest** and **HACS** validation. The release workflow checks that the manifest version matches a pushed `v*` tag. Hosted checks count as passed only when their actual workflow results are inspected.

No mypy, Pyright, coverage threshold, or dedicated translation-alignment command is configured in the repository. Do not report these as existing project requirements. If a check cannot run because tooling, dependencies, credentials, or network access are unavailable, report it as **not run** and explain why.
