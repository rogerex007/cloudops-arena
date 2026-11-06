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

## Current repository state at handoff (2026-11-05)
- `main` README identifies MVP release **0.1.1**.
- Subsequent local work adds authenticated starter ZIPs, evaluation requests/retries, a lease-based worker, GitHub App personal-owner OAuth/installation access, and a disposable networkless KVM mission-02 plan judge. Use `infra/edge/compose.evaluator.yaml` together with the base edge Compose file. The App must be registered and configured locally before real source authorization/scoring. VM plan and atomic-score tests passed locally; GitHub push/manual OIDC requests and participant SSE progress are implemented with the revision-2 starter workflow; the complete mission-02 Actions flow through Cloudflare was verified with the user. Technical deliveries now use Actions only (portal SHA POST retired with 410). Mission-03 uses `aws-event-driven-runtime-v1`: an unprivileged Python handler integration judge with Floci DynamoDB/EventBridge/SQS inside KVM, not Lambda-service deployment. Positive and negative real-VM cases passed, with a temporary-table real-VM grade awarding 20 points once. The participant workflow/guide were added to `rogerex007/gameday-roger-mesa`; its first real Actions run reached the judge and correctly rejected the unfinished Orders stub. API suite: 142 passed; TS/Vite and mission-02 VM regression passed. See `docs/mission-03.md`. Mission-04 uses `aws-event-driven-resilience-v1`: root-owned append-only simulated-operation accounting, service attribution, duplicate/partial-batch checks, native Floci SQS retries `[1,2]`, DLQ and recovery. Real-VM positive/negative cases and a temporary-table real-VM 30-point/replay test passed. Mission-02/03 real-VM regressions passed; mission-04 API suite: 157 passed. Workflow/guide added to the participant test repo; its consumers must implement optional OPERATIONS_URL calls. Busy executors get a bounded 60-second wait and mission-04 Re-run jobs enables retry. A new real mission-04 Actions run reached the judge and correctly failed operation accounting; the participant consumers still need OPERATIONS_URL. See `docs/mission-04.md`. Managed Lambda/runtime provisioning and later mission validators remain pending. See `docs/github-actions-live.md`. See `docs/github-app-and-runner.md`.
- Capacity work now targets 50 registered individuals and 50 global outstanding evaluations, with two VM executions, host/cgroup/disk admission checks, FIFO/requeue/expiry and participant/instructor queue visibility. A temporary-table 50-admission test and two real parallel VM grades passed. A temporary-event 50-registration/300-read Nginx test passed (P95 joins ~1.0s, reads ~0.6s). Current API suite: 168 passed; TypeScript/Vite passed. See `docs/capacity-50.md`. This does NOT implement persistent playground Terraform apply/reuse or 50 live labs; that remains pending.
- Instructor entry is now `/instructor` (including children); public landing no longer exposes an admin entry. Instructor tab sessionStorage is independent of participant localStorage, and legacy admin tokens migrate only on the instructor route. All admin APIs still require the signed admin role. Web checks: 6 session/render tests and TS/Vite passed; API suite 177 passed, including administrative-role regressions. Local Nginx route/auth probes passed. Cloudflare path policy requires dashboard configuration; at initial external check the root and Actions were public and admin dashboard protected, but instructor UI/admin login still lacked Access. See `docs/instructor-access.md` and `scripts/check-access-routes.py`.
- Present: basic participant/instructor UI, event creation with individual/team mode, team invitations, DynamoDB transactions for capacity, simple quiz scoring, leaderboard, manifest-driven missions, signed GitHub webhook, Floci Docker Compose, a Terraform example stack, unit tests including registration flows.
- Not yet complete or verified for production: in-browser code editor/terminal, full lab orchestration/provision/reset/destroy, GitHub App/repo lifecycle, live auditorium screen, real-time updates, production auth/MFA/rate limiting, robust event indexes and load tests, operational dashboards/alerts, verified Floci-Terraform integration, and a secure unattended 100-participant experience. Do **not** describe as production-ready.
- Some workflows are templates and resilience integration tests include TODOs; do not award points merely because a placeholder workflow passed.
- Local demo credentials/test invitation codes are explicitly development-only.

Persistent playground pilot (2026-11-05): `apps/playground` and standalone
`infra/edge/compose.playground-pilot.yaml` verified two concurrent private KVM
VMs, reviewed Terraform apply, managed Lambda/EventBridge/SQS/DynamoDB flow,
clean shutdown/restart persistence and another order after resume. Full cycles
were ~115 seconds; combined container peak 6.25 GiB. Operator-only reference
template, no participant code, public endpoints or scoring. HTTP API Gateway
entry, live-lab incidents, shared evaluator admission, durable scheduling,
participant console/auth and 50-session load remain pending. New one-hour pack
is deliberately `game-packs/aws-event-driven-60/manifest.draft.yaml`, outside
the catalog. Preserve existing pack/events. Preprovision before a one-hour event;
do not imply 50 simultaneous VMs. See `docs/playgrounds.md` and recorded report.

Playground integration deployed (2026-11-05): `compose.playgrounds.yaml` adds a
private single-replica SQLite FIFO manager. `/api/v1/participant/playground`
GET/POST derives the lab from current membership; the portal shows Mi playground,
reference-template provisioning, a timestamped inventory and resume/refresh.
No participant code, Actions deployment or new grading is enabled. Global kernel
locks on `vm-slots` bound playgrounds and evaluations together to two VMs.
Two synthetic participants verified origin auth, separate lab IDs, real apply,
inventory, resume, third-VM rejection, revocation and end-event disk cleanup.
An unrelated concurrent request was preserved. Expiry is two hours after initial
request; finished events revoke reads immediately and clean up after work stops.
Use `scripts/deploy-edge.sh` (all three Compose files), not base-only deployment.
API suite: 190 passed; web session/render tests and TS/Vite passed. The one-hour
pack stays draft pending participant-code updates, managed-Lambda incidents,
live-lab evidence/scoring, prewarming and 50-session tests. See docs/playgrounds.md.

Playground provenance correction (2026-11-05): the public reference-template
prepare/refresh flow was withdrawn after it misleadingly showed infrastructure
for a participant with no delivery. Participant GET now returns
`awaiting_deployment` and no snapshot; POST rejects reference provisioning with
409 after membership/event checks. The web shows Sin despliegue del participante,
no inventory and no prepare button. Existing reference disks are preserved until
normal expiry. The private manager/pilot remain for operator tests. Do not expose
their snapshots as participant work; enabling real inventory requires verified
commit -> successful apply -> assigned lab provenance. Current Actions plan
approval is NOT an apply. API suite: 191 passed.

Mission-02 persistent deployment implemented (2026-11-06 UTC): Actions requests
support operation plan/deploy. Plan cannot score; deploy uses verified GitHub
source and aws-event-driven-deploy-v1, applies a reviewed saved plan in a new
persistent KVM generation, then reboots and checks inventory. The worker writes
DEPLOY#team in the same conditional transaction as result/completion/points;
previous approvals deploy with zero extra points. Public inventory requires
matching receipt/manager provenance; reference snapshots remain hidden. Kit
revision 3 has a commented deploy step for the learner to add. Platform reference
workflow includes it. Positive/negative real VMs, atomic receipts and 14 points
once, plan zero points and legacy approval preservation passed with synthetic
records; API 197 passed, web/TS/Vite passed. Real GitHub OIDC deploy awaits the
participant updating the workflow. Mission03/04 still use ephemeral fixtures;
persistent handler updates/incidents, generation retirement, prewarm/load remain
pending. See docs/mission-02-deploy.md and validation report. Deploy uses worker
PLAYGROUND_MANAGER_URL via compose.playgrounds.yaml; no new secrets.

Deployment transport regression fixed: DynamoDB returns attempt as Decimal;
worker now explicitly converts it to int before JSON encoding /deploy payloads.
The real Actions submission previously failed before reaching the manager. A
regression test now exercises execute_plan with Decimal('2') through the actual
JSON transport encoder. API suite: 198 passed. Worker-only hotfix deployed;
technical-error recovery resubmits the same saved commit/provenance through the
normal registration checks (no manual grading or direct score changes).

Real Actions deployment recovery verified: the original OIDC-authenticated deploy
request was retried with its saved commit/provenance after the Decimal fix. The
worker refetched authorized source, applied it, checked persistence and finished
terraform_deployment_passed with a matching receipt; existing approval awarded
zero extra points. Participant inventory through Nginx/API was checked for the
same commit (3 functions, 2 tables, 4 queues). The original GitHub job had already
failed; its historical conclusion stays red until a fresh workflow run.

Workshop experience deployed (2026-11-06 UTC): removed LOCAL DEMO and the web
demo-award control; redesigned mission focus/navigation, private console and hint
shop, verified in Firefox desktop/mobile. Completed unique missions earn 10
virtual coins by default; wallet credits derive from SUB records, purchases have
unique HINT receipts and atomic spent/membership/deadline checks. Public mission
payloads strip hint content. Hint costs 3/6 are manifest data. Team mode shares
wallet/purchases, individual mode isolates them. API quiz/registration/repo link
and hints enforce server mission deadlines. Activation accepts duration_minutes;
pause freezes remaining time, resume restores it; new events time their first
mission. Legacy untimed events remain so until instructor activation. Expiry
closes new writes; already-admitted technical jobs can finish. No auto-next mission.
Manager owners table now counts 50 participant/team slots rather than attempts;
candidate failures preserve the canonical lab, committed receipts permit
retirement, periodic reconciliation recovers lost acks, active operations drain
on shutdown. New verified deployment renews two-hour TTL; reads do not. API 213,
web 8, TS/Vite, real VM successor/rollback, concurrent hints, expiry/pause,
50-session/450-read origin load (P95 59.8ms) passed. Full event-scale deployment
and persistent runtime03/04 still pending. See docs/workshop-experience.md and
docs/validation/lab-experience-2026-11-06.json. No secrets or existing scores reset.

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
