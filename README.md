# CloudOps Arena

**Reusable platform for technology GameDays, hands-on workshops and team challenges.**

CloudOps Arena is a Game Pack-driven platform. The platform owns the event lifecycle, participants, teams, missions, scoring and instructor controls. Each Game Pack supplies the learning content, challenges, validators and lab requirements. Lab providers are kept separate so a workshop can use an emulator such as Floci or a real AWS sandbox when appropriate.

> **Current release: 0.1.1 — runnable MVP / foundation.** It includes a local participant portal, instructor console, DynamoDB-backed API, Game Pack manifest, quiz scoring, signed GitHub `workflow_run` webhook handling, a Floci local environment and a Terraform example for the first AWS Event-Driven Game Pack. It is not yet a production-ready public SaaS or a fully unattended 100-person lab orchestrator. See [Known limitations](docs/known-limitations.md).

## Product principles

La experiencia del taller incorpora reloj autoritativo por misión, monedas por
finalización y pistas compradas sin restar puntos. El laboratorio mantiene un
cupo por participante y retira generaciones antiguas después de confirmar el
reemplazo. Consulta [operación del taller](docs/workshop-experience.md) para
activar tiempos, pausar, administrar la partida y conocer las pruebas realizadas.

El piloto de playgrounds persistentes y la variante de una hora se describen en
[Playgrounds](docs/playgrounds.md). Misión 02 admite validar y desplegar desde
Actions: el plan no puntúa; el apply verificado publica el inventario del commit
en «Mi playground». Descarga el kit revisión 3 y agrega su paso de deploy.
No se muestra infraestructura de referencia como trabajo del participante.
Véase [misión 02: deploy](docs/mission-02-deploy.md).
En Linux/KVM, `./scripts/deploy-edge.sh` despliega API, web, evaluador y gestor con
el límite compartido de dos VMs. No elimina los volúmenes existentes.

1. **One engine, many Game Packs.** Do not hard-code a specific workshop into the platform.
2. **Provider-neutral lab lifecycle.** A Game Pack declares what it needs; a provider adapter determines where it can run.
3. **No participant AWS keys.** Students interact with the portal and GitHub. Lab execution runs through controlled, isolated runners.
4. **Validate evidence, not button clicks.** Points for technical missions come from verified test results or signed GitHub webhooks, not a participant claiming success.
5. **Cost and cleanup are first-class.** Labs are temporary, constrained and destroyed after the event.

## Repository layout

```text
cloudops-arena/
├── apps/
│   ├── api/                    # FastAPI API; DynamoDB single-table model; JWT sessions
│   └── web/                    # React + TypeScript participant and instructor UI
├── game-packs/
│   └── aws-event-driven/       # First Game Pack: event-driven serverless order system
│       ├── manifest.yaml
│       ├── functions/           # Orders, Payments and Inventory Lambda handlers
│       ├── terraform/           # Terraform resources targeting Floci or AWS
│       └── tests/               # Integration smoke test
├── infra/
│   ├── local/                  # Docker Compose + Floci local emulator
│   └── aws-control-plane/      # Terraform foundation for AWS-hosted control plane
├── scripts/                    # Local start, Terraform and packaging scripts
├── docs/                        # Architecture, security, runbooks and Game Pack contract
└── .github/workflows/           # Example validation and lab workflows
```

## Quick start: local MVP

### Run source checks

Install the API development dependencies and run the static/unit checks:

```bash
python -m pip install -r apps/api/requirements-dev.txt
./scripts/check-project.sh
```


### Prerequisites

- Docker Engine and Docker Compose v2.
- Internet access on first start to pull container images and install the web dependencies.
- A browser.
- Optional for the separate Terraform lab: Terraform 1.10+ and access to the Floci endpoint.

The local Floci container mounts the Docker socket because Floci launches Docker-backed Lambda runtimes. **Only run this Compose stack on a disposable, isolated development/lab machine. Access to `/var/run/docker.sock` is effectively root-level access to that host. Do not expose Floci port 4566 to the internet or to an untrusted network.**

### Start the platform

From the repository root:

```bash
docker compose -f infra/local/compose.yaml up --build -d
```

Open:

- Participant portal on the host: <http://localhost:5173>
- Participant portal from another laptop on the same LAN: `http://<HOST-LAN-IP>:5173`
- API health (host-only): <http://localhost:8000/health>
- API docs (host-only): <http://localhost:8000/docs>
- Floci endpoint (host-only): <http://localhost:4566>

The browser calls the API through the same-origin `/api` reverse proxy in Nginx. This is important: do not bake `http://localhost:8000` into the frontend, because each student's browser would interpret `localhost` as that student's own laptop. Only the web port is exposed to the LAN; API and Floci remain bound to loopback on the host.

The Compose stack starts Floci, creates the `CloudOpsArena` DynamoDB table, seeds a demo event and launches the API and frontend.

### Demo access and registration modes

The local-only demo seed creates a team-mode event but does not pre-create teams. Students register using the event code. The first student creates the team and receives a one-time invitation code/link; teammates use that invitation to join.

| Field | Demo value |
|---|---|
| Event code | `CLOUDOPS-TEAM` |
| Instructor username | `admin` |
| Instructor password | `change-me-now` |

The instructor can create additional events in either **team** or **individual** mode. Team events let a participant create a team and invite colleagues; individual events automatically create a private leaderboard entry for each participant. Invitation codes are stored as hashes and shown only once to the team creator.

These predictable event and instructor credentials are **for local demonstration only**. Do not use them for an actual event or public deployment. The seed is idempotent and will not overwrite an existing event's scores or registrations.

### Stop the platform

Stop containers but preserve local Floci data:

```bash
docker compose -f infra/local/compose.yaml down
```

Remove containers **and all local emulator data**:

```bash
docker compose -f infra/local/compose.yaml down -v
```

The second command is destructive: it deletes the local Floci volume, including the seeded event and all demo registrations and scores.

## Local Terraform + Floci lab

The first Game Pack contains Terraform for:

- API Gateway v2 HTTP API.
- Orders Lambda.
- EventBridge custom event bus and routing rule.
- Payments and Inventory SQS queues, each with a DLQ.
- Payments and Inventory Lambda consumers.
- DynamoDB orders and idempotency tables.
- IAM roles and policies for the functions.

The provider sends Terraform API calls to `http://localhost:4566`. Lambda code runs in Docker containers managed by Floci and therefore uses the internal Compose hostname `http://floci:4566`. These endpoints are intentionally separate.

```bash
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_DEFAULT_REGION=us-east-1

./scripts/run-floci-lab.sh
```

The script runs `terraform init`, `fmt`, `validate` and `plan`. It does **not** apply by default. To create the emulated resources:

```bash
APPLY=true ./scripts/run-floci-lab.sh
```

Then run the integration smoke test:

```bash
cd game-packs/aws-event-driven/terraform
export ORDERS_API_URL="$(terraform output -raw orders_api_url)"
export AWS_ENDPOINT_URL=http://127.0.0.1:4566
export NAME_PREFIX=arena-team-01
python -m pip install boto3
python ../tests/smoke_test.py
```

Destroy the lab:

```bash
cd ../../..
./scripts/destroy-floci-lab.sh
```

> The Floci/ Terraform stack is a learning emulator, not proof of complete AWS fidelity. Validate important behaviors in a real AWS sandbox before relying on them in production.

## Creating a new event

1. Log in to the instructor console.
2. Choose the participation mode: **individual** or **teams**. For team mode, define the maximum team size and event capacity.
3. Create the event and share its event code with participants.
4. In team mode, the first participant creates a team and receives a one-time invitation link/code. Teammates register with that invitation. In individual mode, each participant is assigned an individual leaderboard entry automatically.
5. Open or pause the event and activate missions from the instructor console.

The API also exposes `GET /api/v1/admin/game-packs` for the currently available Game Packs. Event creation API: `POST /api/v1/admin/events`.

## GitHub workflow validation

### Register an evaluation request

Mission 02 includes **Download starter kit (.zip)** in the participant portal.
It supplies the correct repository layout, Terraform base, Lambda exercise stubs
and a Spanish browser-only upload guide. The archive is versioned with the Game
Pack and includes a file-hash manifest. Only registered participants with the
mission active or completed can download it; official validators, quiz answers,
credentials and reference Lambda implementations are excluded.

Participants submit technical missions exclusively through GitHub Actions OIDC.
The event must be open and the matching mission active; the commit is taken from
the signed identity, not pasted into Arena. The old participant SHA POST returns
410. The portal discovers Actions deliveries and shows their live stages.

Mission 02 has separate plan and deploy operations: the plan grants no technical
points; deploy applies verified commit files in a private persistent VM and
atomically publishes evidence, inventory provenance and points. Starter revision
3 asks the learner to add the deploy step. See [mission 02](docs/mission-02-deploy.md).
Mission 03 grades the
Orders/Payments/Inventory handlers against DynamoDB, EventBridge and SQS inside
Floci in the same isolation model. The judge invokes Python handlers rather than
the Lambda service; it does not apply participant Terraform. Download the
mission-03 guide/workflow from the portal without overwriting existing code.
Mission 04 adds observable duplicate protection, partial failures, native SQS
retries/DLQ and recovery with a root-owned simulated-operation receiver. It awards
30 points once and requires adapting the consumers to `OPERATIONS_URL`.
See [mission 03](docs/mission-03.md), [mission 04](docs/mission-04.md), [Actions setup](docs/github-actions-live.md)
and [runner setup](docs/github-app-and-runner.md).

Only one evaluation may be pending per team across missions. Failed/blocked
commits can be retried from Run workflow with `retry`, up to five attempts.
Previous approvals remain valid and cannot award points twice.

### Existing workflow webhook

The edge preview disables legacy workflow-based grading with
`GITHUB_LEGACY_SCORING_ENABLED=false`. Starter workflow checks and file presence
do not award lab points; the isolated official validator grades authorized plans. The API now also defaults to disabling this legacy path; it remains an explicit
compatibility setting only.

The API endpoint is:

```text
POST /api/v1/webhooks/github
```

Configure a GitHub webhook for the `workflow_run` event and use the same secret as `GITHUB_WEBHOOK_SECRET`. The API validates `X-Hub-Signature-256`, checks for a completed successful run, matches the repository to a team, maps the workflow file path to a mission in `manifest.yaml`, then awards points idempotently.

Register a team's repository with the instructor token:

```bash
curl -X PATCH \
  "http://localhost:8000/api/v1/admin/events/<EVENT_ID>/teams/team-001/github" \
  -H "Authorization: Bearer <INSTRUCTOR_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"repo_name":"your-org/team-001","repo_url":"https://github.com/your-org/team-001"}'
```

The mission-02/03/04 starter workflows coordinate the official VM judge through OIDC on GitHub-hosted runners. Root workflow examples skip when `ARENA_EVENT_ID` is unset. Later mission workflows are still templates and cannot approve official evaluations.

## AWS-hosted control plane foundation

For a restricted preview hosted on the local Linux machine at `arena.costacorp.net`,
see [Cloudflare Tunnel preview](docs/cloudflare-preview.md). This is a separate
deployment from the local demo and does not yet implement participant runners.

A separate Terraform foundation lives in `infra/aws-control-plane`. It provisions a DynamoDB table, API Lambda, HTTP API Gateway, CloudFront distribution and a private S3 origin.

Before deploying:

1. Review and harden the authentication model; the current MVP uses environment-configured admin credentials and signed JWTs.
2. Generate a strong random `jwt_secret` and admin password.
3. Build the Lambda package using `scripts/build-api-lambda.sh`.
4. Set `cors_origins` to the actual CloudFront origin.
5. Review AWS costs, quotas, IAM permissions, rate limits, logging and data retention.
6. Apply the Terraform in a dedicated AWS account and deploy the web bundle using `scripts/deploy-web.sh`.

The web deployment script requires AWS CLI, Node.js/npm and Terraform. The Lambda build script requires Docker. See [Deployment notes](docs/deployment.md).

## Main API endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/api/v1/public/events/{event_code}` | Look up an event and its registration mode |
| POST | `/api/v1/auth/join` | Register individually or join a team using its invitation |
| POST | `/api/v1/auth/create-team` | Create a team and issue a one-time invitation code/link |
| POST | `/api/v1/auth/admin/login` | Instructor login |
| GET | `/api/v1/participant/dashboard` | Participant missions and team progress |
| POST | `/api/v1/participant/missions/{id}/answer` | Submit a quiz checkpoint |
| POST | `/api/v1/actions/evaluations` | Request a technical evaluation using signed GitHub Actions OIDC |
| GET | `/api/v1/actions/evaluations/{event_id}/{id}` | Read an evaluation using GitHub Actions OIDC |
| POST | `/api/v1/participant/missions/{id}/evaluations` | Retired: returns 410; use the Actions workflow |
| GET | `/api/v1/participant/missions/{id}/materials` | Download the authenticated, versioned starter ZIP |
| GET | `/api/v1/leaderboard` | Team leaderboard |
| GET | `/api/v1/admin/dashboard` | Instructor overview |
| GET | `/api/v1/admin/game-packs` | Available Game Packs |
| POST | `/api/v1/admin/events` | Create event with individual or team participation mode |
| PATCH | `/api/v1/admin/events/{id}/status` | Open, pause or finish event |
| POST | `/api/v1/admin/events/{id}/activate-mission` | Activate a mission |
| PATCH | `/api/v1/admin/events/{id}/teams/{team}/github` | Bind team repository |
| POST | `/api/v1/webhooks/github` | Receive signed GitHub workflow events |

Interactive API documentation: `/docs`.

## License

MIT. See [LICENSE](LICENSE).

El kit revisión 2 permite solicitar la evaluación oficial desde GitHub Actions
con OIDC y ver sus etapas en vivo en Arena. Configura la ruta de máquinas de
Cloudflare y la variable del evento siguiendo
[GitHub Actions y progreso en vivo](docs/github-actions-live.md).

Para eventos de 50 participantes, el despliegue edge incorpora una cola global
de 50 entregas y dos VMs simultáneas, posiciones de espera y protecciones de
memoria/disco. Las pruebas de origen con 50 registros y 300 lecturas pasaron;
[capacidad medida, límites y configuración](docs/capacity-50.md). Esto controla
las evaluaciones actuales, no implementa aún playgrounds persistentes.

La consola del instructor se abre en `/instructor`; la portada solo muestra
participantes y sus sesiones se conservan por separado. Configura Cloudflare
Access únicamente para el panel y sus APIs siguiendo
[la guía de acceso del instructor](docs/instructor-access.md).
