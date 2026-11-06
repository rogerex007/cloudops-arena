# Known limitations — MVP 0.1.1

This repository is a substantial starting implementation, not a finished production SaaS. The following work remains before the event can run fully unattended at 100 participants:

1. **Authentication hardening:** replace demo environment-based admin credentials with Cognito/OIDC, add MFA, short sessions, revocation, registration rate limits and abuse controls. New team invitation codes are hashed at rest and displayed only to the team creator; the legacy demo event may still contain old plaintext codes.
2. **Admin event management:** the instructor UI can configure individual/team participation and event capacity, but it does not yet provide full event history, CSV export or repository provisioning.
3. **GitHub App:** personal-owner OAuth with PKCE, installation-scoped read access and a participant authorization UI are implemented. Account-owner App registration/local credentials are required; live personal-owner OAuth and repository access were verified on this host. Organization repositories, automated repository creation and authorization-revocation webhooks remain pending. Legacy participant workflow scoring is disabled in the edge deployment.
4. **Execution orchestrator:** requests, exclusive leases, retries/recovery and metadata preflight are implemented. The evaluator override adds mission-02 KVM Terraform plan grading with source/blob verification, policy checks, no guest network and atomic scoring. Positive/negative VM tests and temporary-table score/replay tests passed on this host. Mission-04 now checks sequential/batch duplicates, partial failures, native Floci SQS retries/DLQ and recovery, with simulated operations recorded by the judge. Managed Lambda runtime deployment, concurrent/crash-window guarantees, queue indexes, cancellation and load testing remain pending. See [mission 04](mission-04.md). Push/manual OIDC requests and authenticated SSE progress are implemented; The user confirmed the mission-02 Actions flow through Cloudflare. Mission-03 Python handler integration now has positive/negative real-VM tests; it does not invoke the Lambda service. See [mission 03](mission-03.md). See [Actions setup](github-actions-live.md). See [runner setup](github-app-and-runner.md).
5. **Terraform isolation:** do not run participant-supplied Terraform with the API role or on a shared privileged runner. The revision-2 starter workflow only coordinates requests; the official judge creates one isolated VM per evaluation, serially on this host.
6. **Floci compatibility:** the independent two-VM playground pilot applied the reviewed sample stack and verified managed Lambda → EventBridge → SQS → Lambda → DynamoDB plus clean-restart persistence with pinned versions. HTTP entry via API Gateway v2 and retries/DLQ with managed Lambdas remain unverified; existing resilience grades invoke handler subprocesses. See [pilot evidence](playgrounds.md).
7. **Game Pack validators:** the initial quiz is validated by the API. The GitHub mappings exist; some workflow files are templates. Mission-04 now uses the official OIDC/VM judge rather than its previous self-hosted template. Later mission validators remain pending; simulated-operation tests do not prove production exactly-once behavior.
8. **Frontend:** participant registration supports individual mode and team creation/invitation, and the web container reverse-proxies `/api` so LAN clients do not call their own `localhost`. No embedded code editor, browser terminal, public Arena Screen, or WebSocket/live leaderboard is implemented yet. In this MVP, students follow mission instructions and work with GitHub/tooling separately. The TypeScript check and Vite production build passed on this host; evaluation states, GitHub authorization, authenticated starter downloads and live evaluation stages are now supported.
9. **Scalability:** some discovery and dashboard paths use DynamoDB scans. The edge deployment now bounds outstanding evaluations at 50 and executes two VMs, with per-event queue positions, resource admission checks and jittered polling. A 50-registration/300-read origin test passed. Add GSIs and further load tests before many concurrent events; this does not implement persistent playground provisioning. See [capacity](capacity-50.md).
10. **Observability and audit:** structured logs and CloudWatch infrastructure foundations exist, but dashboards, alarms, full audit trail and abuse detection remain to be implemented.
11. **Cost controls:** no hard cost ceiling can be guaranteed by AWS Budgets alone. Add quotas, IAM guardrails, constrained resource allowlists, cleanup verification and per-event usage reports.
12. **Test status:** API regressions, TypeScript/Vite builds, Floci evaluation/score transactions and a real KVM mission-02 Terraform plan were verified locally. Live GitHub OAuth, repository authorization, real VM progress streaming and SSE through Nginx passed on this host. The user confirmed a complete mission-02 Actions run through Cloudflare and nonduplicate scoring. Full runtime provisioning, later mission validators, recovery and event-scale load have not been verified.

Do not advertise the platform as fully automated until these controls and integrations have been implemented and load-tested.

The workshop UI now has mission clocks with server-enforced closure, earned coins
and purchased hints. Participant capacity is counted separately from generations,
with receipt-gated retirement, lost-ack reconciliation and graceful shutdown.
213 API tests, 8 web tests, real VM replacement/currency checks and a local-origin
50-session/450-read test passed. This is not a full-workshop simulation with 50
concurrent deployments; VM concurrency remains two and managed-runtime missions
03/04 remain pending. See [workshop operation](workshop-experience.md).

The [mission-02 deploy flow](mission-02-deploy.md) now applies verified commit files
in a persistent VM, checks inventory after reboot and atomically publishes its
receipt and points. Reference snapshots remain hidden. Real positive/negative
KVM, receipt/score and plan-only tests passed; the deploy flow through real GitHub
OIDC awaits the participant's updated workflow. Missions 03/04 still grade in
ephemeral fixtures, not these persistent resources. Previous-generation cleanup,
prewarming, 50-session load and the one-hour pack remain pending.
