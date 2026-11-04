# Deployment notes

## Local deployment

Use Docker Compose instructions in the root README. The local stack is intended for development only.

## AWS control plane foundation

`infra/aws-control-plane` is a Terraform foundation for a serverless control plane:

- DynamoDB single table with on-demand billing and point-in-time recovery.
- API Lambda packaged from FastAPI/Mangum.
- HTTP API Gateway.
- CloudWatch log group.
- Private S3 bucket for the static frontend.
- CloudFront distribution with Origin Access Control.

### Build API Lambda artifact

Requires Docker:

```bash
./scripts/build-api-lambda.sh
```

This produces `build/api-lambda.zip`.

### Apply infrastructure

Requires Terraform 1.10+ and AWS credentials with permission to provision the resources. Use a dedicated AWS account and review the plan.

```bash
cd infra/aws-control-plane
terraform init
terraform fmt -recursive
terraform validate
terraform plan \
  -var='jwt_secret=REPLACE_WITH_LONG_RANDOM_SECRET' \
  -var='admin_password=REPLACE_WITH_LONG_RANDOM_PASSWORD' \
  -var='cors_origins=["https://YOUR_CLOUDFRONT_DOMAIN"]'
terraform apply
```

For the first apply, use a temporary known frontend origin or apply the API and distribution in stages, then re-apply with the final CloudFront origin. Do not commit a `.tfvars` file containing secrets. Prefer a secret manager and a federated deployment role for production.

### Build and upload frontend

Requires Node.js/npm and AWS CLI:

```bash
./scripts/deploy-web.sh
```

The script builds the Vite bundle against the API URL, syncs it to the private bucket and invalidates CloudFront.

## Important caveats

This foundation is not a production deployment recipe without further security review. Admin credentials are currently environment variables on the Lambda and the MVP login has no MFA, password hashing or rate limiting. Before opening registration publicly, implement a real identity provider, secret retrieval/rotation, request throttling, audit trails, webhook delivery deduplication, and a complete lab runner isolation model.
