# Floci compatibility notes

Repository inspected: <https://github.com/floci-io/floci>.

Floci describes itself as a free, open-source local AWS emulator. It exposes AWS-shaped service endpoints at port `4566` and documents support for AWS SDKs, AWS CLI, Terraform, OpenTofu and CDK. Docker-backed Lambda execution uses real containers. Its README lists EventBridge, SQS, DynamoDB, Lambda, API Gateway v2, IAM and CloudWatch among supported services.

## Why it fits this Game Pack

The first Game Pack uses:

- API Gateway v2 HTTP API.
- Lambda (Python 3.12 in the example).
- EventBridge custom bus, rule and SQS targets.
- SQS queues and redrive policies.
- DynamoDB tables.
- IAM roles and inline policies.
- Lambda event-source mappings.

The Game Pack pins the HashiCorp AWS provider to the 6.x line and uses service-specific Floci endpoints through the provider's `endpoints` configuration.

## Local endpoint split

Terraform running on the host calls `http://localhost:4566`. Lambda runtime containers launched by Floci need to call the Floci service over the Compose network at `http://floci:4566`. These are separate settings:

- `endpoint_url`: Terraform provider endpoint.
- `lambda_endpoint_url`: endpoint injected into the emulated Lambda function environment.

The Compose file sets `FLOCI_SERVICES_LAMBDA_DOCKER_NETWORK=cloudops-arena_default` so Floci-managed Lambda containers can resolve the `floci` service name.

## Compatibility is not the same as AWS fidelity

A successful local apply is not proof that every AWS edge case, IAM condition, retry timing, Lambda runtime behavior, API Gateway integration or service quota is identical to real AWS. The first validation target is the happy path and controlled failure behavior in the supplied Game Pack. Important outcomes must later be checked in a real, isolated AWS sandbox.

## Local state and cleanup

The local Floci service uses persistent storage so resources survive a container restart. Terraform state for this sample is local to the lab directory. For actual multi-team execution, use a separate state key and an isolated runner per team; do not point 20 concurrent teams at a single local state file.

## Useful upstream docs

- [Floci README](https://github.com/floci-io/floci)
- [Terraform with Floci](https://github.com/floci-io/floci/blob/main/docs/getting-started/terraform.md)
- [Multi-account isolation](https://github.com/floci-io/floci/blob/main/docs/configuration/multi-account.md)
- [Lambda](https://github.com/floci-io/floci/blob/main/docs/services/lambda.md)
- [EventBridge](https://github.com/floci-io/floci/blob/main/docs/services/eventbridge.md)
