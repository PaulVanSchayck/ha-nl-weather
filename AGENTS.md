# AI Agent Instructions

NL Weather is a Home Assistant custom integration for KNMI weather observations and forecasts, alerts, precipitation nowcasts, radar imagery, and MQTT notifications. The integration is in `custom_components/nl_weather/`; tests are in `tests/`.

## Before editing

1. Read [AI_POLICY.md](AI_POLICY.md) and [home-assistant.md](home-assistant.md), plus any applicable instructions in the directory hierarchy of the files being changed.
2. Inspect the relevant implementation, callers, tests, manifest, dependencies, and CI workflow. Check recent history if intent or compatibility is unclear.
3. Follow the task's acceptance criteria and keep the diff limited to the requested outcome. Do not perform unrelated refactors or add dependencies without evidence and justification.

## Validation and reporting

Run relevant checks from [home-assistant.md](home-assistant.md). Review the final diff for correctness, security, scope, and unintended changes. Report only commands actually run and their real outcomes; identify failures and checks that were unavailable or not run. Never claim unverified success.
