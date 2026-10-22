# AI Agent Instructions

NL Weather is a Home Assistant custom integration for KNMI weather observations and forecasts, alerts, precipitation nowcasts, radar imagery, and MQTT notifications. The integration is in `custom_components/nl_weather/`; tests are in `tests/`.

## Before editing

1. Read [AI_POLICY.md](AI_POLICY.md) and [home-assistant.md](home-assistant.md), plus any applicable instructions in the directory hierarchy of the files being changed.
2. Inspect the relevant implementation, callers, tests, manifest, dependencies, and CI workflow. Check recent history if intent or compatibility is unclear.
3. Follow the task's acceptance criteria and keep the diff limited to the requested outcome. Do not perform unrelated refactors or add dependencies without evidence and justification.

## Mandatory pre-commit validation

Before committing, review affected assertions and add regression tests without weakening valid expectations. Format modified Python files and run the repository's CI commands:

```bash
python3 -m ruff check .
python3 -m ruff format . --check
PYTHONPATH=. pytest
```

Fix failures and rerun checks. If required checks cannot run, disclose which checks were skipped and why, and obtain explicit user approval before pushing unvalidated changes. Review the final diff for correctness, security, scope, and unintended changes. After pushing, inspect GitHub Actions and do not merge while required checks are failing or pending. Never claim unverified success.

## Validation and reporting

Follow [home-assistant.md](home-assistant.md) for additional checks. Report only commands actually run and their real outcomes.
