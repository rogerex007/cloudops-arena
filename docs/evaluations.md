# Automatic evaluation

The worker polls deliveries every three seconds and processes one at a time.
It is separate from the API, runs non-root with a read-only filesystem and resource
limits, and has no host Docker socket, published ports or GitHub App private key.

## Execution modes

The default `compose.yaml` uses metadata-only preflight. It checks a public commit
and required files, reports failed/blocked results and releases the pending slot.
File presence cannot approve a mission or grant points.

Adding `compose.evaluator.yaml` enables mission 02 technical grading in a disposable
KVM VM. Configure and authorize the GitHub App as described in
[the complete setup guide](github-app-and-runner.md). This flow supports personal
public/private repositories installed on the App. Organization repos remain unsupported.
The revision-2 starter workflow supports push/manual OIDC requests and live stages;
see [Actions setup](github-actions-live.md).

The API verifies ownership, installation access, commit/tree/blob hashes and the
trusted Game Pack version. It returns only allowlisted source bytes to the worker.
The VM has no network device, uses pinned offline providers, and starts Floci on
loopback. A root-owned judge runs Terraform as an unprivileged user: HCL policy,
format normalization, init, validate and plan. It checks allowed resource types,
counts, IAM actions and required routing references. No apply or Lambda execution
occurs; passing mission 02 is not proof of runtime behavior for later missions.

Results arrive through a dedicated root-only virtio channel. The executor verifies
run ID, source digest, validator and loopback-only evidence. The worker independently
checks the digest and atomically records a successful result, unique submission,
14 points and slot release. Current membership and authorization are rechecked in
that transaction. The separate repository-link point remains unchanged.

## Lifecycle

```text
pending -> preparing -> running -> passed | failed | blocked
               |                              |
               +-> failed | blocked           +-> retry -> pending
```

One active request is allowed per individual/team across missions. Repeated
submissions return the existing record. Explicit failed/blocked retries are
limited to five per delivery and accepted only while the event and mission are
active. Corrected source uses a new SHA. Accepted requests may finish after event
closure. The dashboard polls every five seconds while an evaluation is active.

Claims carry unique leases: two minutes in metadata mode or ten minutes in VM
mode. Expired leases become blocked and release the matching slot. Lease-token
conditions prevent stale workers from overwriting results or releasing newer jobs.
QEMU has a 270-second deadline and per-file bounds; overlays and ISO files are
removed only after its process exits. Host power loss can leave scratch directories
that need inspection. Polling uses scans; indexed queues, cancellation, quotas,
backoff and event-like load testing remain future work.

## Verification on this host

The submitted public commit passed an actual KVM plan with 28 resources and the
expected routing; an added external module was rejected. The guest had only the
loopback network interface, and scratch job directories were empty afterwards.
Atomic scoring and replay protection passed on a temporary Floci table without
changing the real event. Live GitHub OAuth remains gated on App registration and
its local credentials. Mocked authorization tests do not replace that account setup.

## Operation

```bash
docker compose --env-file infra/edge/.env \
  -f infra/edge/compose.yaml -f infra/edge/compose.evaluator.yaml \
  up --build -d api web worker runner
docker compose --env-file infra/edge/.env \
  -f infra/edge/compose.yaml -f infra/edge/compose.evaluator.yaml logs --tail=50 worker
```

Use both files for technical grading. QEMU runs in the executor container; no host
QEMU/libvirt packages are required. New mission validators, source authorization
revocation events, automated push triggers and runtime lab provisioning remain
separate work. Keep the legacy participant workflow scoring path disabled.

## Actions-only submissions and mission 03

The participant SHA POST is retired (410); the registration service is called
only by verified Actions identities. Portal retries are removed. Mission 03 uses
a separate reviewed runtime validator with 20-point atomic scoring and a distinct
three-file source allowlist. See [mission 03](mission-03.md).

Mission 04 adds `aws-event-driven-resilience-v1`, bound to mission-04 and
`resilience_flow_passed`, with 30-point idempotent scoring. Runner-busy HTTP 409
is retried for at most 60 seconds inside the existing execution lease. See
[resilience contracts and limits](mission-04.md).
