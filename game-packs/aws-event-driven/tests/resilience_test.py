"""Resilience checkpoint. Payment Lambda must already be deployed with FAIL_PAYMENTS=true."""
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
sqs = boto3.client("sqs", **aws)


def create_order(order_id: str) -> None:
    req = urllib.request.Request(
        f"{api_url}/orders",
        data=json.dumps({"orderId": order_id, "customerId": "resilience-test", "total": "75.00"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        if response.status != 201:
            raise AssertionError(f"Expected 201, got {response.status}")


# Two deliveries for the same business order must produce one idempotency record per consumer.
duplicate_id = f"gameday-duplicate-{int(time.time())}"
create_order(duplicate_id)
create_order(duplicate_id)
for _ in range(30):
    payment = ddb.get_item(TableName=f"{prefix}-idempotency", Key={"eventId": {"S": duplicate_id}, "service": {"S": "payments"}}).get("Item")
    inventory = ddb.get_item(TableName=f"{prefix}-idempotency", Key={"eventId": {"S": duplicate_id}, "service": {"S": "inventory"}}).get("Item")
    if payment and inventory:
        break
    time.sleep(1)
assert payment and inventory, "Duplicate-delivery test did not reach both consumers"

# Payments is deliberately failing. The event must reach the configured DLQ.
failed_id = f"gameday-dlq-{int(time.time())}"
create_order(failed_id)
dlq_url = sqs.get_queue_url(QueueName=f"{prefix}-payments-dlq")["QueueUrl"]
dlq_record_found = False
for _ in range(180):
    received = sqs.receive_message(QueueUrl=dlq_url, MaxNumberOfMessages=10, WaitTimeSeconds=2)
    for message in received.get("Messages", []):
        envelope = json.loads(message["Body"])
        detail = envelope.get("detail", envelope)
        if str(detail.get("orderId")) == failed_id:
            dlq_record_found = True
            break
    if dlq_record_found:
        break
    time.sleep(1)
else:
    raise AssertionError("Failed payment message did not arrive in the DLQ within 6 minutes")

inventory = ddb.get_item(TableName=f"{prefix}-idempotency", Key={"eventId": {"S": failed_id}, "service": {"S": "inventory"}}).get("Item")
assert inventory, "Inventory consumer should still process the order while Payments is failing"
print(json.dumps({"status": "passed", "duplicate_order": duplicate_id, "dlq_order": failed_id, "inventory_processed": True, "payment_dlq_record_found": True}))
