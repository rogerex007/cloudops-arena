# Authoring a Game Pack

## 1. Create the package directory

```text
game-packs/my-new-pack/
├── manifest.yaml
├── missions/
├── validators/
├── incidents/
├── infrastructure/
└── docs/
```

## 2. Add the manifest

Use `game-packs/aws-event-driven/manifest.yaml` as the reference implementation. Every mission must have a stable unique ID, title, type, points, duration and instructions. Keep secrets and answer keys server-side; the API strips `answer`, `validator_secret` and `expected_value` from participant-facing mission data.

## 3. Validation types

Recommended validation types:

- `quiz`: answer is checked by the API; simple knowledge checkpoint.
- `github_workflow`: a trusted `workflow_run` success maps to a mission.
- `integration_test`: a dedicated runner executes tests against the team's lab.
- `instructor_review`: requires an instructor's signed review for subjective work.

Never accept participant-supplied `passed: true` or point totals from the browser.

## 4. Provider requirements

Declare provider requirements separately from mission content. A pack should state whether it requires Floci, real AWS, a local Docker runtime, Terraform, a minimum provider version, specific services, region, estimated runtime and cleanup steps. A provider compatibility check should run before event registration opens.

## 5. Versioning

Use semantic versions. Once an event starts, lock its Game Pack version and manifest checksum so that changing the package does not retroactively change scoring or challenge instructions.
