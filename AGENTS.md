# CloudOps Arena — Instructions and project context for Codex

This file is the durable handoff of the product vision and current implementation. Read this file **and** `README.md`, `docs/architecture.md`, `docs/security-model.md`, and `docs/known-limitations.md` before editing. Respect repository code as the source of truth when this document describes intended rather than implemented behavior.

## Product vision
CloudOps Arena is a reusable GameDay/workshop platform, not a one-off university event website. Instructors should configure events and use versioned, pluggable **Game Packs**; learners enter through a single browser portal, complete missions, develop/test solutions, and earn evidence-based points. Instructors control events, incidents, teams, and a live auditorium leaderboard. Future Game Packs may cover AWS event-driven systems, DevOps, DevSecOps, Kubernetes, and AI engineering. Keep the engine technology/provider-agnostic.

## First event and audience
- First workshop title: **“Todo empieza con un evento”** (event-driven serverless architectures with AWS, Terraform, and DevOps).
- Audience: systems engineering students, many beginners in AWS, Terraform and DevOps; explain concepts progressively, provide friendly error messages, keep onboarding friction low, and do not assume local CLI installations.
- Event context: auditorium capacity around 400; only attendees with laptops participate in hands-on labs. Initial operational target is ~100 active students, initially modelled as 20 teams of 5; configurable capacity and team size are required, not hard-coded.
- Workshop duration target ~4 hours, with gamified challenges, automatic technical validation, failures/retries/DLQs, and an optional AI bonus.
- Student-facing ideal: scan a QR, join the portal, work from the browser, without personal AWS accounts/long-lived credentials.
- **Registration modes must be configurable per event**: individual (private progress/leaderboard entity) or team. In team mode the creator becomes team leader, receives a one-time invitation link/code, and invites members; joining enforces team and event capacity atomically. Preserve this flow and test it.

## Architecture and decisions
- Control plane: React + TypeScript web app (`apps/web`), FastAPI backend (`apps/api`), DynamoDB-compatible data model, JWT-based MVP sessions, instructor console, scoring and Game Packs.
- Game Packs: versioned declarative manifests. First pack at `game-packs/aws-event-driven/`, with Orders -> EventBridge -> SQS Payments/Inventory -> Lambda consumers, DynamoDB and retries/DLQs; Terraform IaC; GitHub Actions examples.
- Lab provider abstraction: initial Floci emulator and AWS sandbox (`apps/api/app/providers`). **Providers currently only implement connectivity/capability checks, not end-to-end provisioning**.
- Terraform is the initial IaC engine; OpenTofu may be supported later. Floci is an AWS-compatible emulator, not an IaC engine. Support both emulated and real AWS labs via provider-specific adapters, and design future providers as plugins.
- Initial cost posture: one controlled AWS account for the platform and approved team labs, serverless where reasonable, no costly NAT/RDS/EKS by default; Floci can reduce AWS service charges but still requires Docker-host compute.
- Keep API/control plane separate from isolated **lab execution runners**. The API must never execute arbitrary participant Terraform or code. Use reviewed/allowlisted plans, least-privilege roles, per-team isolation, approval where appropriate, and automated cleanup. Do not expose Floci/Docker socket to attendees; synthetic Floci account IDs are *not* a security boundary.
- GitHub: signed `workflow_run` webhook and scoring exist. Future work includes GitHub App installation, automated repository provisioning, strong webhook deduplication, and per-team trusted workflow/branch checks. AWS real deployments should use OIDC, not static AWS keys.
- Scoring requires verified evidence, conditional/atomic idempotent writes, and auditable awarding. Prevent repeated submissions or forged browser claims from incrementing points.
- The web portal uses **same-origin `/api` proxy**; never hard-code `localhost:8000` in client-side calls for LAN users.

## Current repository state at handoff (2026-11-04)
- `main` README identifies MVP release **0.1.1**.
- Present: basic participant/instructor UI, event creation with individual/team mode, team invitations, DynamoDB transactions for capacity, simple quiz scoring, leaderboard, manifest-driven missions, signed GitHub webhook, Floci Docker Compose, a Terraform example stack, unit tests including registration flows.
- Not yet complete or verified for production: in-browser code editor/terminal, full lab orchestration/provision/reset/destroy, GitHub App/repo lifecycle, live auditorium screen, real-time updates, production auth/MFA/rate limiting, robust event indexes and load tests, operational dashboards/alerts, verified Floci-Terraform integration, and a secure unattended 100-participant experience. Do **not** describe as production-ready.
- Some workflows are templates and resilience integration tests include TODOs; do not award points merely because a placeholder workflow passed.
- Local demo credentials/test invitation codes are explicitly development-only.

## Work priorities
1. Make onboarding/registration reliable end-to-end with clear individual/team choice, leader invitation lifecycle, event/team limits, error messages and tests.
2. Add a robust instructor event administration experience (open/pause/finish; capacity/team config; participant/team status).
3. Build a reusable Game Pack registry/schema/validation and versioning, without branching on hard-coded game IDs.
4. Build browser-based mission workspace/editor integrated with source control; do not execute arbitrary code in web/API containers.
5. Add isolated lab runner orchestrator and lifecycle (`preflight`, `provision`, `validate`, `reset`, `destroy`) with allowlisted infra, quotas, idempotency, retries and audited cleanup.
6. Validate one end-to-end **Floci + Terraform + Lambda + EventBridge + SQS + DynamoDB** scenario (including idempotency and DLQ), pin tested versions.
7. Add live public Arena Screen, production security hardening, load testing and event-day runbook.

## Development expectations
- Prefer small reviewable changes with tests; do not rewrite the working project unnecessarily.
- Preserve public API compatibility unless explicitly planning a migration.
- For API changes, add/update pytest tests. For web changes, run TypeScript checks and production build. For IaC, run `terraform fmt`, `validate`, a plan where feasible; run integration tests when Docker/Floci are available. State clearly what could not be run.
- Document new environment variables, privilege boundaries, schema changes and deployment steps.
- Do not commit secrets, bearer tokens, AWS access keys, instructor passwords or personal data.
- Review `docs/security-model.md` before any work involving auth, IAM, Floci, webhooks, Terraform execution, or public endpoint exposure.
- Avoid claims of “100% automatic” until user journey, provisioning, scoring, incident injection, recovery and cleanup have been tested under event-like load.
- When a feature request is broad, first inspect the relevant files and propose a narrowly scoped implementation; implement safe incremental improvements.

## Key starting points
- `README.md` — setup, commands, API list and release scope.
- `apps/api/app/main.py` — event, registration, scoring and GitHub webhook routes.
- `apps/web/src/App.tsx` / `apps/web/src/api.ts` — portal and client API calls.
- `apps/api/tests/test_registration_flows.py` — invitation/individual/team tests.
- `game-packs/aws-event-driven/manifest.yaml` — first Game Pack contract.
- `infra/local/compose.yaml` — development environment.
- `docs/event-day-runbook.md` — operational guidance.
