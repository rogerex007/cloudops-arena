import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config

from .config import settings


def dynamodb_client():
    return boto3.client(
        "dynamodb",
        endpoint_url=settings.dynamodb_endpoint_url or None,
        region_name=settings.dynamodb_region,
        aws_access_key_id="test" if settings.dynamodb_endpoint_url else None,
        aws_secret_access_key="test" if settings.dynamodb_endpoint_url else None,
        config=Config(retries={"max_attempts": 3, "mode": "standard"}),
    )


def table_resource():
    dynamodb = boto3.resource(
        "dynamodb",
        endpoint_url=settings.dynamodb_endpoint_url or None,
        region_name=settings.dynamodb_region,
        aws_access_key_id="test" if settings.dynamodb_endpoint_url else None,
        aws_secret_access_key="test" if settings.dynamodb_endpoint_url else None,
        config=Config(retries={"max_attempts": 3, "mode": "standard"}),
    )
    return dynamodb.Table(settings.dynamodb_table_name)


def query_partition(pk: str) -> list[dict]:
    table = table_resource()
    response = table.query(KeyConditionExpression=Key("PK").eq(pk))
    items = response.get("Items", [])
    while response.get("LastEvaluatedKey"):
        response = table.query(
            KeyConditionExpression=Key("PK").eq(pk),
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        items.extend(response.get("Items", []))
    return items


def get_item(pk: str, sk: str) -> dict | None:
    return table_resource().get_item(Key={"PK": pk, "SK": sk}).get("Item")


def scan_items(filter_expression=None) -> list[dict]:
    table = table_resource()
    kwargs = {"FilterExpression": filter_expression} if filter_expression is not None else {}
    response = table.scan(**kwargs)
    items = response.get("Items", [])
    while response.get("LastEvaluatedKey"):
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"], **kwargs)
        items.extend(response.get("Items", []))
    return items
