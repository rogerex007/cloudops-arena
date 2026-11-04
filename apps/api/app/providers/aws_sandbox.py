import boto3
from botocore.exceptions import BotoCoreError, ClientError

from .base import ProviderStatus


class AwsSandboxProvider:
    """Connectivity check for an AWS sandbox role; does not provision resources."""

    def __init__(self, region: str = "us-east-1"):
        self.region = region

    def health(self) -> ProviderStatus:
        try:
            identity = boto3.client("sts", region_name=self.region).get_caller_identity()
            return ProviderStatus("aws-sandbox", True, "cloud", f"Connected to account {identity.get('Account')}")
        except (BotoCoreError, ClientError, OSError) as exc:
            return ProviderStatus("aws-sandbox", False, "cloud", str(exc)[:240])

    def capabilities(self) -> list[str]:
        return ["lambda", "eventbridge", "sqs", "dynamodb", "api-gateway-v2", "terraform", "oidc"]
