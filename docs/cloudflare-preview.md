# Restricted preview on arena.costacorp.net

This standalone deployment is for a restricted instructor preview on the local Linux x86_64
host with Docker Engine and Compose. The base file starts metadata preflight;
the evaluator override adds GitHub-authorized mission 02 KVM grading, as described
in [the App/runner guide](github-app-and-runner.md). Capacity for 100 participants
has not been established. Floci persistence and
end-to-end lab execution must be tested on this host before an event. Use an Access email
allowlist while production identity, audit, evaluation trust and isolation remain
unfinished; this is not a public event deployment.

## Host and execution boundary

The current host has an Intel i5-11400 (6 cores / 12 threads), approximately
32 GB RAM, and `/dev/kvm` available. The existing demo uses port 5173; this
standalone preview uses loopback port 5174 and a separate storage volume.
The evaluator override starts a disposable KVM plan runner without access to the
host Docker socket or control-plane network. Runtime lab provisioning for later
missions remains separate work. Start with one evaluation at a
time and measure resource use before increasing concurrency.

Local startup has been verified on this Linux host: the portal, API health,
instructor login and authenticated dashboard returned HTTP 200; the demo-award
route returned 404. Storage initialization completed successfully. The user
verified Cloudflare login and event/participant registration. The KVM plan passed
positive/negative integration tests. Storage recovery, live GitHub OAuth and
event-scale load testing remain pending.

## 1. Prepare and check locally

From the repository root on this machine:

```bash
sh scripts/setup-edge.sh
docker compose --env-file infra/edge/.env -f infra/edge/compose.yaml config --quiet
docker compose --env-file infra/edge/.env -f infra/edge/compose.yaml up --build -d
curl --fail http://127.0.0.1:5174/health
```

For the current Linux/KVM installation with evaluations **and** the participant
playground console, use `./scripts/deploy-edge.sh` instead of the base-only `up`
command above. It combines the evaluator and playground overrides, preserving
their private networks, persistent lab disks and shared VM ceiling. See
[the integrated playground deployment](playgrounds.md).

Open http://127.0.0.1:5174. Read the instructor username/password locally from
`infra/edge/.env`. No demo event is seeded; create a fresh event from the instructor
console. This stack has a separate data volume from the local demo. There are no
host ports for the API or storage, no Docker socket mounts, and demo mode is off.
The tunnel is opt-in and is not started by these commands.

The stack also starts a separate metadata-only evaluation worker. It checks public
GitHub commits and required files, reports failed/blocked results and releases the
pending slot. It does not execute Terraform or start participant VMs. See
[the evaluation guide](evaluations.md).

Mission 02 now offers an authenticated starter ZIP and browser upload guide. The
preview sets `GITHUB_LEGACY_SCORING_ENABLED=false` so starter workflow successes
cannot award lab points; quiz scoring and the repository-link point still work.

The generated `.env` and `.secrets/` are ignored by Git. Do not run plain
`docker compose config` in shared logs: its rendered configuration contains secrets.
The example uses moving image tags for initial compatibility testing; replace
`FLOCI_IMAGE` and `CLOUDFLARED_IMAGE` with tested x86_64-compatible tags or digests
before the event. The connector must support `--token-file` (>= 2025.4.0).

## 2. Restrict the hostname in Cloudflare Access

In the Cloudflare account managing `costacorp.net`, create a self-hosted Access
application for **arena.costacorp.net**, covering the entire hostname. Create an
Allow policy for your instructor email only and configure the login method.
Set this up before adding the tunnel route. Check your account's Access user
limits before extending an allowlist to participants.

This deployment does not independently validate Access JWTs at the origin. It
relies on the Cloudflare policy and on keeping the origin on loopback/private
Docker networks. Do not add a direct public/LAN route to the origin.

## 3. Create the tunnel and route

Create a remotely managed Cloudflare Tunnel called `cloudops-arena-host` in the
Cloudflare dashboard. Save only its connector token, using a local editor, as:

```text
infra/edge/.secrets/cloudflare-tunnel-token
```

Do not paste the token into chat, commit it, or put it in a shell command/history.
The directory is private; Compose mounts the token as a read-only secret. Keep
the file readable by the cloudflared container user. On Linux, a file with mode 600
owned by your account may be unreadable to the container. Keep the containing
`.secrets` directory at mode 700 and grant read permission to the file for the
container, or configure an appropriate ACL. This is a connector token, not an account API token.

Add a published application route:

| Field | Value |
|---|---|
| Hostname | `arena.costacorp.net` |
| Service type | HTTP |
| Service URL | `web:80` |

`web` is the Docker service name reachable by the tunnel container. Do not use
`localhost:5174` here: localhost inside that container means the connector itself.
Cloudflare manages HTTPS at the public hostname; HTTP remains within Docker.
If the DNS name already exists, inspect it before changing any existing record.

## 4. Start and verify the restricted preview

```bash
docker compose --env-file infra/edge/.env -f infra/edge/compose.yaml --profile tunnel up -d tunnel
docker compose --env-file infra/edge/.env -f infra/edge/compose.yaml logs --tail=50 tunnel
```

Open https://arena.costacorp.net from another network. An unauthenticated visitor
must encounter Access login; a non-allowlisted email must be denied. After Access
login, verify Arena login, event creation, and participant registration with a test
event. Verify `https://arena.costacorp.net/health` after Access authentication;
it proxies the API's real health endpoint, rather than only testing Nginx.

Auth endpoints are limited to 5 requests/minute per client IP with a small burst;
other API endpoints are limited to 10/second. These are initial preview settings,
not load-tested event capacity. The edge uses Cloudflare's client-IP header; do
not expose its loopback origin externally. No frontend API URL is needed: `/api`
stays on the same public origin. `CORS_ORIGINS` is the exact HTTPS hostname.

On the university network, verify Docker image downloads, the tunnel's outbound
connectivity and future runner connectivity to GitHub with IT. No router port
forwarding is required. Keep this host powered, awake and connected during use.

## GitHub webhook boundary

The planned URL is
`https://arena.costacorp.net/api/v1/webhooks/github`. The whole-hostname Access
policy intentionally blocks GitHub webhooks during this first browser preview:
GitHub cannot complete interactive Access login. Do not bypass Access for all
of `/api` to make callbacks work.

Before enabling Actions scoring, implement trusted evaluation runs and webhook
hardening. Then configure a separate path-specific Access application that
bypasses interactive login only for the exact webhook path, leaving HMAC
verification mandatory with the generated `GITHUB_WEBHOOK_SECRET`. Verify that
unsigned requests are rejected and other paths remain protected. The future
OIDC submission endpoint will need its own explicit machine-authenticated route;
it is not implemented by this deployment.

## Stop and preserve data

```bash
# Disconnect public access, keeping the local preview available:
docker compose --env-file infra/edge/.env -f infra/edge/compose.yaml --profile tunnel stop tunnel
# Stop the complete stack, preserving the volume:
docker compose --env-file infra/edge/.env -f infra/edge/compose.yaml --profile tunnel down
```

Do not add `-v` unless intentionally deleting event data. Back up the storage
volume with the service stopped before any real event or image upgrade. API
credentials are currently environment variables visible to Docker administrators.
See [security-model.md](security-model.md) and [known-limitations.md](known-limitations.md)
for the remaining production work, especially authentication and runner isolation.

References: [Cloudflare Tunnel setup](https://developers.cloudflare.com/tunnel/get-started/),
[Access applications](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/),
[connector token files](https://developers.cloudflare.com/tunnel/reference/run-parameters/).

## Abrir participantes y conservar Access para el instructor

La consola ahora está en `/instructor`. Sustituye la protección general del
hostname por los cuatro patrones y la política Allow del instructor descritos
en [esta guía](instructor-access.md). Conserva el túnel y el Bypass acotado de
Actions. No abras todo `/api/*`; la API administrativa y su login deben seguir
protegidos. La SPA por sí sola no cambia políticas remotas de Cloudflare.
