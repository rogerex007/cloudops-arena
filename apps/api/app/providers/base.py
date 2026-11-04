from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProviderStatus:
    provider: str
    reachable: bool
    mode: str
    detail: str


class LabProvider(Protocol):
    """Contract implemented by each laboratory provider adapter.

    Provisioning is intentionally not exposed as arbitrary shell execution.
    Provider adapters must consume a reviewed Game Pack and a constrained plan.
    """

    def health(self) -> ProviderStatus: ...

    def capabilities(self) -> list[str]: ...
