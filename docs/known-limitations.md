# Known limitations — MVP 0.1.1

This repository is a substantial starting implementation, not a finished production SaaS. The following work remains before the event can run fully unattended at 100 participants:

1. **Authentication hardening:** replace demo environment-based admin credentials with Cognito/OIDC, add MFA, short sessions, revocation, registration rate limits and abuse controls. New team invitation codes are hashed at rest and displayed only to the team creator; the legacy demo event may still contain old plaintext codes.
2. **Admin event management:** the instructor UI can configure individual/team participation and event capacity, but it does not yet provide full event history, CSV export or repository provisioning.
3. **GitHub App:** GitHub webhook signature verification and workflow-to-mission scoring are implemented; GitHub App installation, repository creation, team binding UI and webhook delivery deduplication are not.
4. **Execution orchestrator:** lab provider adapters currently check connectivity/capabilities only. A separate isolated runner service must be built to run Terraform, tests, reset and destroy operations.
5. **Terraform isolation:** do not run participant-supplied Terraform with the API role or on a shared privileged runner. The supplied workflow is a template and requires one constrained runner/workspace per team.
6. **Floci compatibility:** the sample Terraform stack has not been applied in this container. Validate provider versions and the precise behavior of API Gateway v2, EventBridge → SQS, SQS → Lambda, retries and DLQ on the pinned Floci release.
7. **Game Pack validators:** the initial quiz is validated by the API. The GitHub mappings exist; some workflow files are templates. The resilience workflow still contains a TODO and must be replaced with assertions before awarding production points.
8. **Frontend:** participant registration supports individual mode and team creation/invitation, and the web container reverse-proxies `/api` so LAN clients do not call their own `localhost`. No embedded code editor, browser terminal, public Arena Screen, or WebSocket/live leaderboard is implemented yet. In this MVP, students follow mission instructions and work with GitHub/tooling separately. The TypeScript source was syntax/type-checked with local stubs, but a full Vite production build was not run because npm dependency installation timed out in the editing environment.
9. **Scalability:** some discovery and dashboard paths use DynamoDB scans. Add GSIs and pagination before hosting many concurrent events.
10. **Observability and audit:** structured logs and CloudWatch infrastructure foundations exist, but dashboards, alarms, full audit trail and abuse detection remain to be implemented.
11. **Cost controls:** no hard cost ceiling can be guaranteed by AWS Budgets alone. Add quotas, IAM guardrails, constrained resource allowlists, cleanup verification and per-event usage reports.
12. **Test status:** Python syntax and configuration files should be checked locally; Docker, Terraform and AWS provisioning were not available in the generation environment. Do not interpret this scaffold as a successful deployment.

Do not advertise the platform as fully automated until these controls and integrations have been implemented and load-tested.
