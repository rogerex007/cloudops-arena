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

## 6. Downloadable starter materials

An optional mission-level `materials` object declares a title, revision,
participant instructions and an explicit list of `{source, destination}` files.
Sources are relative to the Game Pack directory; destinations are relative to the
ZIP/repository root. Keep exercise stubs under `starter/` rather than bundling
reference implementations. Include a license, browser upload guide and ignore file.
See mission 02 in the reference pack for the complete mapping.

The authenticated `GET /api/v1/participant/missions/{id}/materials` endpoint
resolves the participant's event and pack; it permits active or completed
missions, including reading materials while the event is paused. It never accepts
a client-supplied source path. The archive contains deterministic file ordering,
fixed ZIP timestamps and `ARENA-KIT.json` with pack version, mission, materials
revision and SHA-256 hashes. No directory wrapper is added. The response is
private/non-cacheable, and filenames are sanitized.

The builder rejects absolute/traversing paths, duplicate destinations, external
symlinks, validators/tests, environment files, private keys and Terraform state
or secret variable files. Each file is limited to 256 KiB, with at most 100 assets
and 2 MiB of total source bytes. Only public metadata (title, instructions,
filename) is sent to the dashboard; the source mapping stays on the server.
Review explicit asset lists for accidental answers or secrets before releasing
a pack; the builder cannot infer sensitive content from arbitrary file text.

The sample kit workflow runs structural Terraform checks on GitHub-hosted runners.
It does not prove completion of the lab. The edge deployment sets
`GITHUB_LEGACY_SCORING_ENABLED=false` so that such workflow successes cannot grant
mission points through the legacy webhook. Other deployments retain the legacy
default for compatibility and must explicitly disable it before using
participant-controlled workflows. This flag does not affect quiz scoring or the
separate repository-link point.

Los contratos de ejecución revisados del primer pack incluyen plan (mission-02),
runtime (mission-03) y resilience (mission-04). Los pares misión/validador/código
de éxito se registran explícitamente en `evaluation_validators.py`; añadir una
entrada al manifest no habilita ejecución arbitraria ni permite reutilizar la
aprobación de otro juez. Resilience recibe solo los tres handlers allowlisted.
