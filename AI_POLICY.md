# AI-Assisted Development Policy

Integration-specific engineering rules belong in [home-assistant.md](home-assistant.md). This file governs evidence, security, scope, and reporting for AI-assisted changes.

## Evidence and precedence

- Inspect actual source, callers, tests, configuration, dependency declarations, workflows, and applicable instructions before proposing or making changes. Use repository history when necessary to distinguish current intent from obsolete behavior.
- Follow task-specific requirements and acceptance criteria over generic recommendations, subject to security constraints and established repository requirements. Surface conflicts or missing information instead of silently guessing.
- Distinguish verified facts from assumptions and recommendations. Do not fabricate versions, API behavior, file paths, commands, test results, or repository conventions.

## Scope and change control

- Make the smallest complete change that satisfies the task. Avoid speculative features, unrelated refactoring, generated churn, and unjustified dependencies.
- If the task is limited to documentation or tooling, do not change application behavior.
- Preserve runtime dependency declarations, CI behavior, entity identity, and supported interfaces unless an intentional change is required and justified.
- Keep each setting and dependency declaration authoritative in one place; do not introduce conflicting or duplicate configuration.
- Inspect the final diff and confirm that only intended files changed.

## Correctness and compatibility

- Trace changes through callers, data flow, lifecycle, and tests. Handle missing, malformed, and unavailable external data deliberately.
- Maintain asynchronous execution and resource lifecycle correctness. Avoid blocking I/O on the event loop, preserve cancellation, and release resources owned by the integration.
- Catch expected errors at the correct boundary, preserve useful exception context, and do not hide unexpected programming errors.
- Add focused regression tests for behavior changes and bug fixes, including relevant edge cases and failure paths.
- Keep dependencies compatible with the manifest, the Home Assistant APIs in use, Python exercised by CI, and the existing dependency-management approach. Do not promote a workflow-only transitive dependency pin into runtime requirements without a demonstrated need.

## Security and diagnostics

- Never log API tokens, credentials, passwords, private keys, personal data, or sensitive request/response bodies.
- Redact secrets and sensitive identifiers from diagnostics, exceptions, fixtures, and examples. Do not place credentials in URLs, command output, snapshots, or documentation.
- Log useful operational context—such as operation and failure category—without exposing sensitive payloads. Avoid noisy duplicate logs or complete response dumps.
- Treat external API responses and user-provided configuration as untrusted input; validate types and structure before use.
- Do not weaken validation, error handling, dependency security, or CI checks merely to make a change pass.

## Validation and communication

- Choose checks appropriate to the changed files and current repository workflows. Run relevant tests, lint/format checks, and validation when feasible.
- A workflow definition is not evidence that the workflow passed in the current task. Never fabricate command output, tool versions, CI status, review results, or successful mutations.
- Mark unavailable checks as **not run** and explain why. Report failures clearly instead of describing them as passes.
- The final report must identify changed files, actual validation results, unavailable checks, and unresolved assumptions or risks.
