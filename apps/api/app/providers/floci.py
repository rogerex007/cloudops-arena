import boto3
from botocore.exceptions import BotoCoreError, ClientError

from ..config import settings
from .base import ProviderStatus


class FlociProvider:
    """Read-only connectivity adapter for a local Floci AWS emulator."""

    def __init__(self, endpoint_url: str | None = None):
        self.endpoint_url = endpoint_url or settings.dynamodb_endpoint_url

    def health(self) -> ProviderStatus:
        try:
            client = boto3.client(
                "dynamodb", endpoint_url=self.endpoint_url,
                region_name=settings.dynamodb_region,
                aws_access_key_id="test", aws_secret_access_key="test",
            )
            client.list_tables()
            return ProviderStatus("floci", True, "emulated", f"Reachable at {self.endpoint_url}")
        except (BotoCoreError, ClientError, OSError) as exc:
            return ProviderStatus("floci", False, "emulated", str(exc)[:240])

    def capabilities(self) -> list[str]:
        return ["lambda", "eventbridge", "sqs", "dynamodb", "api-gateway-v2", "iam", "cloudwatch-logs", "terraform"]
