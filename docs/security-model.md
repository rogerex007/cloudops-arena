# Security model and deployment guardrails

## Current MVP warning

The local stack is for development and demonstration only. It contains demo credentials, predictable team codes, a demo-award route, broad local-emulator credentials and a Floci container with the Docker socket mounted. Do not expose this stack to public networks or use its local configuration for an actual event.

## Trust boundaries

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

## Floci isolation caveat

Floci can namespace resources by account ID. Its documentation explicitly warns that synthetic 12-digit access keys route requests to an account namespace but do not prove that a caller owns that account. Do not treat that mechanism alone as a security boundary between mutually untrusted teams. Use separate emulator instances/VMs or additional enforced identities and network isolation for untrusted execution.

References:
- [Floci multi-account isolation](https://github.com/floci-io/floci/blob/main/docs/configuration/multi-account.md)
- [Floci IAM enforcement](https://github.com/floci-io/floci/blob/main/docs/services/iam.md)
- [AWS IAM best practices](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html)
