"""End-to-end smoke test for an applied Floci lab.

Environment:
  ORDERS_API_URL       Terraform output orders_api_url
  AWS_ENDPOINT_URL     Floci endpoint reachable from this runner (usually localhost)
  NAME_PREFIX          Terraform var.name_prefix
"""
import json
import os
import time
import urllib.request

import boto3

endpoint = os.getenv("AWS_ENDPOINT_URL", "http://127.0.0.1:4566")
api_url = os.environ["ORDERS_API_URL"].rstrip("/")
prefix = os.getenv("NAME_PREFIX", "arena-team-01")
region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

aws = {
    "endpoint_url": endpoint,
    "region_name": region,
    "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID", "test"),
    "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
}
ddb = boto3.client("dynamodb", **aws)

order_id = f"gameday-smoke-{int(time.time())}"
request = urllib.request.Request(
    f"{api_url}/orders",
    data=json.dumps({"orderId": order_id, "customerId": "smoke-test", "total": "125.00"}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(request, timeout=15) as response:
    assert response.status == 201, f"Unexpected API response: {response.status}"
    body = json.loads(response.read().decode())
assert body["orderId"] == order_id

orders_table = f"{prefix}-orders"
for _ in range(20):
    item = ddb.get_item(TableName=orders_table, Key={"orderId": {"S": order_id}}).get("Item")
    if item:
        break
    time.sleep(1)
assert item, "Order was not persisted to DynamoDB"

idem_table = f"{prefix}-idempotency"
processed = set()
for _ in range(30):
    for service in ("payments", "inventory"):
        found = ddb.get_item(TableName=idem_table, Key={"eventId": {"S": order_id}, "service": {"S": service}}).get("Item")
        if found:
            processed.add(service)
    if processed == {"payments", "inventory"}:
        break
    time.sleep(1)
assert processed == {"payments", "inventory"}, f"Consumers did not finish. Processed: {processed}"
print(json.dumps({"status": "passed", "order_id": order_id, "consumers": sorted(processed)}))
