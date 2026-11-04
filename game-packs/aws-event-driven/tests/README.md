# Game Pack test suite

`smoke_test.py` validates the happy path after the Terraform stack is applied to Floci.
It creates an order through API Gateway, verifies persistence in DynamoDB, and waits for both
SQS-triggered Lambda consumers to record their idempotency keys.

Run from a machine that can reach Floci and the deployed API:

```bash
export AWS_ENDPOINT_URL=http://127.0.0.1:4566
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export ORDERS_API_URL="$(terraform -chdir=../terraform output -raw orders_api_url)"
export NAME_PREFIX=arena-team-01
python -m pip install boto3
python smoke_test.py
```

The test uses a unique order ID. It does not test billing, IAM policy enforcement, production
networking, or real AWS service fidelity.
