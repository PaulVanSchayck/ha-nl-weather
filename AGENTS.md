# AI Agent Instructions

NL Weather is a Home Assistant custom integration for KNMI weather observations and forecasts, alerts, precipitation nowcasts, radar imagery, and MQTT notifications. The integration is in `custom_components/nl_weather/`; tests are in `tests/`.

## Before editing

1. Read [AI_POLICY.md](AI_POLICY.md) and [home-assistant.md](home-assistant.md), plus any applicable instructions in the directory hierarchy of the files being changed.
2. Inspect the relevant implementation, callers, tests, manifest, dependencies, and CI workflow. Check recent history if intent or compatibility is unclear.
3. Follow the task's acceptance criteria and keep the diff limited to the requested outcome. Do not perform unrelated refactors or add dependencies without evidence and justification.

## Ruff linting and formatting rules

- Use the repository-pinned Ruff version from `requirements.txt` (`ruff==0.16.7`); do not silently change versions or introduce conflicting Ruff settings.
- Follow Ruff's existing default lint and formatter configuration unless an explicit, reviewed configuration change is requested. Do not disable rules, add blanket `noqa` comments, or exclude files to hide failures.
- Before each commit, **apply** formatting to changed Python files with `python3 -m ruff format <changed-files>`, then run both repository-wide CI checks: `python3 -m ruff check .` and `python3 -m ruff format . --check`. The `--check` command only reports formatting problems; it does not fix them.
- Correct import ordering and other lint diagnostics with focused changes. Use `python3 -m ruff check <changed-files> --fix` only after reviewing the proposed fixes; rerun both checks afterward.
- Treat any nonzero exit code as a failure. Do not claim Ruff passed based on inspection or a successful commit; verify command output or the corresponding GitHub Actions job.

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
