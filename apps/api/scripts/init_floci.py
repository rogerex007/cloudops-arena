import os
import time
import boto3
from botocore.exceptions import ClientError

ENDPOINT = os.getenv("DYNAMODB_ENDPOINT_URL", "http://floci:4566")
REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
TABLE = os.getenv("DYNAMODB_TABLE_NAME", "CloudOpsArena")

client = boto3.client(
    "dynamodb", endpoint_url=ENDPOINT, region_name=REGION,
    aws_access_key_id="test", aws_secret_access_key="test",
)

for attempt in range(30):
    try:
        client.list_tables()
        break
    except Exception:
        if attempt == 29:
            raise
        time.sleep(2)

try:
    client.describe_table(TableName=TABLE)
    print(f"Table {TABLE} already exists")
except ClientError as exc:
    if exc.response["Error"]["Code"] != "ResourceNotFoundException":
        raise
    client.create_table(
        TableName=TABLE,
        KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"}, {"AttributeName": "SK", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    waiter = client.get_waiter("table_exists")
    waiter.wait(TableName=TABLE)
    print(f"Created table {TABLE}")
