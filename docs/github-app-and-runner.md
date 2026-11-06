# GitHub authorization and isolated Terraform evaluation

The mission 02 executor uses a disposable KVM VM, not a GitHub runner registered
in participant repositories. The worker requests verified source from the API,
passes only allowlisted file bytes to the executor, checks the evidence digest,
and atomically records the result, mission submission, score and slot release.
Participant workflows cannot submit passed results or point totals.

## Register the GitHub App once

Open https://github.com/settings/apps/new in the account that will own the App.
Use these settings:

| Setting | Value |
|---|---|
| Name | A unique name, such as CloudOps Arena Costacorp |
| Homepage URL | `https://arena.costacorp.net` |
| Callback URL | `https://arena.costacorp.net/api/v1/github/callback` |
| Request user authorization during installation | Disabled; Arena starts its own PKCE flow |
| Setup URL / Device flow | Leave unset / disabled |
| Webhook Active | Disabled for this integration |
| Repository Contents | Read-only |
| Repository Metadata | Read-only (automatic) |
| Other permissions | No access |
| Installation scope | Any account, so participants can install it on personal repositories |

No Actions write permission, repository administration, user email access or
AWS credentials are required. Keep expiring user access tokens enabled. This
first ownership flow supports repositories owned by personal GitHub accounts;
organization/shared ownership needs an additional permission model.

After creating the App, copy its App ID, Client ID and public slug from its
settings. Generate a Client secret and a private key. Put them locally in:

```text
infra/edge/.secrets/github-app.json
infra/edge/.secrets/github-app.pem
```

The JSON format is shown in `infra/edge/github-app.example.json`. Fill in the
four values in the private JSON file, keeping `app_id` numeric. The PEM file must
contain the complete downloaded private key, including its BEGIN/END lines.
Do not put either file in a participant repository or paste their contents into
chat. The API mounts these files read-only; the worker and VM never receive them.
`sh scripts/setup-edge.sh` creates empty placeholders and a separate runner
authentication secret without replacing existing credentials. The `.secrets`
directory is mode 700. Keep the App files private to your host user (mode 600).
The runner token must remain readable by the non-root executor (mode 644 inside
the private directory).

## Run locally

Requires Linux x86_64, Docker Compose and accessible `/dev/kvm`. The runner image
build downloads Ubuntu packages, Terraform 1.10.5, AWS provider 6.0.0 and Archive
provider 2.7.0, verifying HashiCorp packages against their official SHA-256 files.
The VM contains the local Floci native binary. Allow several GB of image/build
space; initial downloads can take time. Pin tested upstream image digests before
an event. Host QEMU/libvirt packages are not needed: QEMU runs in the executor
container with access to `/dev/kvm` only.

```bash
sh scripts/setup-edge.sh
docker compose --env-file infra/edge/.env \
  -f infra/edge/compose.yaml -f infra/edge/compose.evaluator.yaml \
  up --build -d api web worker runner
```

Use both Compose files for subsequent updates; omitting the evaluator override
returns the worker to metadata-only preflight. The public tunnel remains a
separate service/profile. Recreate API containers after replacing secret files,
since editor atomic replacements can leave an old bind-mounted inode.

## Participant flow

1. Link the participant's own repository in mission 02.
2. Click **Instalar GitHub App** and select only that repository.
3. Return to Arena and click **Autorizar mi repositorio**. Sign in to GitHub with
   the personal account owning that repository.
4. Add the mission workflow and set ARENA_EVENT_ID in GitHub Actions variables.
   Run it while the event and mission are active. Retries use Run workflow with
   retry enabled; the portal no longer accepts pasted SHAs.

OAuth uses a random hashed state, PKCE S256 and a ten-minute, single-use exchange.
The callback verifies the personal repository owner, installation, current Arena
membership, event state and unchanged binding. It stores IDs and verification
metadata rather than GitHub user tokens. The temporary user token is revoked
after the exchange when possible; tokens and refresh tokens are never persisted.
OAuth codes/states are redacted from origin access logs.

The callback is a browser navigation, so the current Cloudflare Access browser
session can protect it. No interactive-login bypass is needed for this OAuth
flow. Actions uses a separate, path-scoped Cloudflare exception and signed OIDC identities; see [Actions setup](github-actions-live.md).

## Execution boundary and grading

The worker obtains source through a token-authenticated internal API endpoint.
The API verifies the installation again, obtains a short-lived installation token
restricted to one repository with Contents read-only, checks the exact commit,
tree and blob SHA-1s, and returns only selected files. GitHub tokens stay outside
the VM. The `/internal/` route is not proxied publicly and also requires the
worker secret and an active evaluation lease.

Each job gets a fresh qcow2 overlay and a read-only ISO. The VM has no network
device or shared host filesystem. Floci is reachable only on guest loopback;
it has no host Docker socket. Terraform runs as an unprivileged guest user,
uses an offline provider mirror and synthetic emulator credentials, and cannot
access the API, storage, App keys or host network. Modules, external data,
additional providers, provisioners, remote backends and unapproved resource
types are rejected. The evaluator normalizes format, initializes, validates,
generates a creation-only plan and checks its expected resource counts, allowed
IAM actions and service routing references. Formatting is normalized in the
disposable copy; it does not fail the provided starter for formatting alone.
It does not apply resources or execute Lambda exercise stubs; those belong to
later missions. A plan grade is not proof of runtime functionality.

A root-owned guest judge writes bounded evidence through a dedicated virtio
channel, inaccessible to the Terraform user. The executor checks the run ID,
source digest and validator identity; participant stdout does not determine
success. The worker independently matches the digest and authorization before
awarding the 14 workflow points. The separate repository-link point is unchanged.
The submission insert is conditional, preventing duplicate scoring.

One VM runs at a time with 2 vCPUs and 1.5 GiB guest RAM. The executor container
is limited to 3 GiB/2 CPUs, runs non-root without capabilities, has no published
ports and uses an internal network. It terminates QEMU after 270 seconds and
removes the per-job disk/ISO only after QEMU exits. Worker execution leases last
ten minutes; failures and expired leases release the matching slot. Host power
loss can leave scratch directories; inspect the runner work volume after a crash.
Treat runner image updates and access to `/dev/kvm` as privileged operations.

## Remaining limits

Creating the GitHub App and installing/authorizing it are required account-owner
actions. The default empty secret files deliberately block execution/awarding;
public repository readability alone is insufficient. This host passed real VM
boot, valid-plan and external-module rejection tests; the guest had only loopback
and scratch directories were empty afterwards. Floci score/replay transactions
passed on a temporary table. Live OAuth must still be exercised after App setup,
along with event capacity and recovery tests.
Automatic triggering from participant `push` via GitHub OIDC, organization repos,
load testing and later mission validators are separate work.

References: [GitHub user authorization](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app),
[installation tokens](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation),
[QEMU system options](https://www.qemu.org/docs/master/system/qemu-manpage.html).

## GitHub Actions y seguimiento

El kit revisión 2 incorpora disparo por push/Run workflow con OIDC y seguimiento
por etapas. Configuración de Cloudflare, variable por evento y límites:
[GitHub Actions y progreso en vivo](github-actions-live.md).
