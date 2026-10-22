# AI Agent Instructions

NL Weather is a Home Assistant custom integration for KNMI weather observations and forecasts, alerts, precipitation nowcasts, radar imagery, and MQTT notifications. The integration is in `custom_components/nl_weather/`; tests are in `tests/`.

## Before editing

1. Read [AI_POLICY.md](AI_POLICY.md) and [home-assistant.md](home-assistant.md), plus any applicable instructions in the directory hierarchy of the files being changed.
2. Inspect the relevant implementation, callers, tests, manifest, dependencies, and CI workflow. Check recent history if intent or compatibility is unclear.
3. Follow the task's acceptance criteria and keep the diff limited to the requested outcome. Do not perform unrelated refactors or add dependencies without evidence and justification.

## Mandatory pre-commit validation

1. Before committing, inspect existing tests and identify assertions affected by the change. Update regression tests only when the intended behavior justifies changing their expectations; do not weaken tests merely to obtain a pass.
2. Apply the configured formatter to modified Python files, then run the same repository-wide checks as CI from the repository root:

   ```bash
   python3 -m ruff check .
   python3 -m ruff format . --check
   PYTHONPATH=. pytest
   ```

3. Fix any failures and repeat the relevant checks until they pass. Review the final diff for correctness, security, scope, and unintended changes.
4. If required checks cannot run in the available environment, state exactly which checks were not run and why. Do **not** create or push a commit without explicit user approval for unvalidated changes. Never claim that a check passed unless its successful execution was verified.
5. After pushing, inspect GitHub Actions results for the new commit. Report failures or pending checks accurately; do not merge while required checks are failing or pending.

## Validation and reporting

Follow the additional checks and compatibility guidance in [home-assistant.md](home-assistant.md). Report only commands actually run and their real outcomes, including unavailable or skipped checks. GitHub status checks protect merges but do not replace pre-commit validation.
