# Security model and deployment guardrails

## Current MVP warning

The local stack is for development and demonstration only. It contains demo credentials, predictable team codes, a demo-award route, broad local-emulator credentials and a Floci container with the Docker socket mounted. Do not expose this stack to public networks or use its local configuration for an actual event.

## Trust boundaries

Workshop clocks are server-owned. New technical submissions, quiz scoring, repo
link awards and hint purchases enforce the active mission's deadline; writes
also condition on it inside their DynamoDB transactions. A browser countdown is
display only. Registered technical deliveries may finish after mission expiry;
end-event and ownership checks still apply. Legacy events without deadlines stay
untimed until an instructor activates a timer.

Coins are derived from unique completion records; purchases use a unique receipt
and conditional spent counter in one transaction with membership/event/deadline
checks. Hint text is excluded from public manifests and sent only for the team's
purchases. Wallets are virtual workshop rewards, independent of leaderboard
points. No participant request chooses cost, balance or reward.

1. Browser is untrusted. It receives only a short-lived portal JWT and public mission content.
2. API is a control-plane service. It must not execute arbitrary Terraform or user code.
3. GitHub webhook is authenticated by HMAC; deliveries must be deduplicated and mapped to an allowlisted repository and workflow path.
4. Lab runner is a separate execution boundary, ideally one ephemeral runner per team or a hardened runner pool with per-job isolation.
5. Lab provider credentials are never delivered to a participant browser or committed to a repository.

## Required before a public event

- Replace demo admin password login with Cognito/OIDC or an equivalent identity provider; use MFA for instructors.
- Store JWT signing material and webhook secrets in Secrets Manager or Parameter Store; rotate them.
- New team invitation codes are hashed at rest and displayed only to the creator. Remove the legacy plaintext-code fallback after existing demo data is migrated; rate-limit code attempts, add lockouts and event expiry.
- Add rate limiting/WAF/API Gateway throttling and request-size limits.
- Use strict CORS origins; do not use `*` with credentialed requests.
- Add short session lifetimes, refresh/revocation semantics and audit logging.
- Add idempotency to GitHub webhook delivery IDs and validate expected workflow path, branch, repository and event state.
- Make scoring policy immutable after event start or audit every change.
- Enforce team capacity atomically (the MVP uses a transaction).
- Separate platform control-plane IAM role from lab deployer roles.
- Restrict Terraform to approved modules/resources. Run `validate`, policy checks, cost estimation and plan review before apply.
- Use a dedicated ephemeral runner per team. Destroy the runner and its workspace after the GameDay.
- Keep Floci private. The Docker socket is effectively host-root access; use a disposable VM and do not mount it into public-facing services.
- Add AWS Budgets, service quotas, SCPs or permissions boundaries where appropriate, plus cleanup verification.

## Pending evaluation requests

The participant evaluation endpoint accepts only a full commit SHA and resolves
the repository from the authenticated participant's stored team binding. It
atomically rechecks event/mission state and membership, and prevents concurrent
pending requests for the same leaderboard entry. Requests do not grant points,
fetch source or execute code. Linking a repository URL does not establish GitHub
ownership; persisted requests are explicitly marked `repository_verified=false`.
Default preflight reads public metadata without passing missions. KVM mode uses
GitHub App OAuth with PKCE and single-use state to verify personal repository
ownership, then scoped read-only installation tokens to verify exact source blobs.
The executor runs Terraform as an unprivileged guest user with no network device,
host shares or real cloud credentials. A root-only evidence channel and matched
source digest gate positive grading. Result, unique submission, score and slot
release are atomic and conditional on lease, membership and authorization. The
API holds App keys; the worker and VM never receive them. See
[the execution boundary](github-app-and-runner.md).
The existing workflow webhook is a separate legacy scoring path and has not
gained these guarantees. The edge preview disables it with
`GITHUB_LEGACY_SCORING_ENABLED=false`; other deployments retain the legacy
default for compatibility and must opt out before distributing participant workflows.

Starter ZIPs require current participant membership and an active/completed
mission. They use explicit pack-local file lists and exercise stubs; validators,
answers, state and environment files are excluded. Source mappings remain
server-side. See [Game Pack materials](game-pack-authoring.md) for archive limits
and the required review of asset content.

## Floci isolation caveat

Floci can namespace resources by account ID. Its documentation explicitly warns that synthetic 12-digit access keys route requests to an account namespace but do not prove that a caller owns that account. Do not treat that mechanism alone as a security boundary between mutually untrusted teams. Use separate emulator instances/VMs or additional enforced identities and network isolation for untrusted execution.

References:
- [Floci multi-account isolation](https://github.com/floci-io/floci/blob/main/docs/configuration/multi-account.md)
- [Floci IAM enforcement](https://github.com/floci-io/floci/blob/main/docs/services/iam.md)
- [AWS IAM best practices](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html)

### Piloto de playground persistente

Mission-02 deploy now adds a private `/deploy` operation accepting only verified
allowlisted commit files and their digest. Source is mounted read-only and
rehashed in the guest. Terraform plan policy is checked before apply, all inside
a VM with no external NIC or real AWS credentials. The worker matches source,
result and deployment identity, then conditionally writes the receipt together
with score/completion under a live lease and current ownership. Plan mode cannot
score. Public inventory requires matching receipt and manager provenance. Failed
attempts remain private. This establishes deployment evidence, not application
correctness, production isolation certification or full event-scale readiness.

Provenance correction: participant GET no longer fetches reference-template
snapshots, and participant POST rejects reference provisioning with 409. The
private manager remains for operator acceptance tests. Its captures must not be
used as evidence of a participant deployment. Re-enabling the console inventory
requires an authorized commit, verified apply and a matching assigned lab; a
successful plan or a root reference-template test is insufficient. The following
integration description documents the earlier reference-only prototype.

The integrated console now has authenticated `/api/v1/participant/playground`
GET/POST routes. The API derives the lab ID from the event and the membership's
leaderboard entry and checks membership on every call; client-provided IDs or
endpoints are ignored. Only curated resource names/counts/timestamps leave the
private manager. It has no scoring permission or platform database credentials.
The template is trusted operator content; participant code deployment is not yet
enabled. The same runner secret authenticates manager RPC and private event-state
checks; no service secret enters the browser or guest. Both execution services
hold kernel locks on a private shared volume, limiting their combined fleet to
two VMs. Finishing an event revokes portal access immediately; disk deletion waits
for running work to stop. See [the console lifecycle](playgrounds.md).

El piloto independiente en `apps/playground` no tiene endpoints HTTP, redes del
control plane, datos de participantes ni permisos de puntuación. Dos VMs sin NIC
externa contienen cada una Docker y Floci. Se habilita explícitamente la escucha
de Floci en la red interna de esa VM para que los contenedores Lambda lleguen al
emulador; esto no debe copiarse al host ni al API. El socket Docker permanece
dentro de la VM. El código operador se monta en un ISO de solo lectura y el canal
serial es root-only. Solo se acepta el template de referencia del repositorio,
no Terraform/código enviado por participantes. La prueba no sustituye las futuras
verificaciones de pertenencia, leases, revocación, cuotas y limpieza para una
consola multiusuario. Véase [alcance del piloto](playgrounds.md).

### Identidad de Actions y progreso del evaluador

Los endpoints `/api/v1/actions/*` exigen OIDC RS256 del emisor fijo de GitHub,
audiencia configurada, vida corta, IDs inmutables coincidentes con la autorización
App, miembro/equipo vigente y rama/workflow permitidos. Un `jti` no registra más
de una solicitud. El SHA proviene del JWT. La excepción de Cloudflare Access
para esta ruta solo elimina el login interactivo; no sustituye esta verificación.
El workflow participante no publica resultados ni puntajes. El stream SSE requiere
sesión y pertenencia al equipo; transmite campos públicos y etapas curadas, sin
secretos ni salida arbitraria. El canal de progreso root de la VM es independiente
del canal de evidencia final. Véase [el flujo](github-actions-live.md).

### Juez de funciones de misión 03

El juez runtime prepara Floci y verifica efectos en DynamoDB/EventBridge/SQS.
Cada handler se importa solo en un proceso UID 2000 dentro de KVM, con límites
y eliminación de descendientes. El módulo de pruebas es root-only; el resultado
retornado por el handler nunca basta para aprobar. El API/worker no importan ni
ejecutan Python del participante. Los validadores oficiales se vinculan a misión
y código de resultado para impedir usar un plan aprobado como evidencia runtime.
Las entregas SHA desde el portal están retiradas y el webhook legacy está
desactivado por defecto. Véase [el alcance de misión 03](mission-03.md).

### Resiliencia y operaciones simuladas de misión 04

El juez root mantiene un registro HTTP append-only en loopback dentro de la VM.
Solo admite POST acotados y vincula la operación al handler activo. No ofrece
lectura/reset al participante. Comprueba todos los contadores, espera las
peticiones al cerrar y vuelve a comprobar antes de aprobar. Esto permite rechazar
una fila de idempotencia sobreescrita que oculta operaciones duplicadas. El fallo
se inyecta antes de marca/operación; no se acredita atomicidad con pagos externos.
La DLQ requiere evidencia nativa SQS; no se simula el traslado mediante un envío
del juez a esa cola. Los procesos siguen aislados de API, worker y host. Véase
[misión 04](mission-04.md) para contratos y límites.

### Admisión y protección de recursos

Las entregas reservan un cupo global mediante la misma transacción de inserción
y lock de equipo; el límite inicial es 50 y cada finalización libera exactamente
uno en su transacción de resultado/puntos. Las VMs se limitan también en el
ejecutor, con reservas de memoria host/cgroup, disco y máximo simultáneo. La
espera no amplía permisos: solo Actions OIDC registra entregas y solo el juez
oficial puede aprobarlas con lease vigente. La UI publica solo posiciones y
agregados de evento, sin identidades de otras entregas. El despliegue de esta
versión se hizo sin entregas antiguas en curso. Véase [capacidad](capacity-50.md).

### Entrada separada de instructor

La SPA reserva `/instructor` y sus hijos para la consola. La portada no ofrece
login administrativo ni reutiliza una sesión legacy de administrador. El token
del instructor vive separado en sessionStorage; la sesión del participante sigue
en sus claves locales. Esto es separación de estado, no autorización ni un
origen distinto. Los endpoints administrativos conservan require_admin y el
login sigue comprobando credenciales. El gateway debe proteger tanto el panel
como `/api/v1/admin*` y `/api/v1/auth/admin*`, mientras registro/participantes y
Actions quedan fuera del login interactivo. La política de Actions exige OIDC
en el backend. Véase [configuración y comprobación](instructor-access.md).

## Public projection links

An instructor can explicitly publish and revoke a per-event scoreboard link.
The random 192-bit link grants only read access to display names, ranks, scores
and event/mission summaries; it grants no participant or admin session. Every
read checks the event's current token against the separate SCREEN index, so an
orphaned old index cannot bypass revocation. Public responses use an explicit
field allowlist and no-store; HTML also sends no-referrer/noindex. This is a
shareable projection, so anyone receiving its link can see the display names.
See [operation](leaderboard-screen.md).
