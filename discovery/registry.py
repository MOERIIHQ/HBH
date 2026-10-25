"""
HBH Discovery Adapter Registry — Phase 1b-GH-2C.

Source-agnostic registry for discovery adapters.

Responsibilities:
- Accept valid DiscoveryAdapter implementations
- Validate the adapter contract at registration time
- Reject duplicate source registration
- Provide deterministic lookup by source name
- Distinguish registered from missing adapters
- List registered adapters in registration order

Does NOT contain:
- HTTP logic
- Source-specific API logic
- Policy or triage logic
"""


from __future__ import annotations

from typing import Any

from hbh.discovery.models import ADAPTER_CONTRACT_VERSION
from hbh.discovery.models import (
    AdapterResult,
    AdapterStatus,
    BountyCandidate,
    RunContext,
    make_bounty_candidate,
    make_run_context,
    make_adapter_result,
)


class AdapterRegistry:
    """Source-agnostic registry for DiscoveryAdapter implementations.

    Runtime responsibility: determine WHICH registered adapters should execute.
    The registry does NOT execute adapters or fetch candidates — that is the
    DiscoveryEngine's responsibility (GH-2A).
    """

    def __init__(self) -> None:
        self._adapters: dict[str, DiscoveryAdapter] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, adapter: DiscoveryAdapter) -> None:
        """Register a discovery adapter.

        Validates the adapter contract and rejects duplicate source names.

        Args:
            adapter: A DiscoveryAdapter implementation.

        Raises:
            TypeError: If *adapter* does not satisfy the DiscoveryAdapter contract.
            ValueError: If *adapter.source* is empty or already registered.
        """
        self._validate_adapter_contract(adapter)

        source = adapter.source
        if source in self._adapters:
            raise ValueError(
                f"Adapter for source {source!r} already registered"
            )
        self._adapters[source] = adapter

    def unregister(self, source: str) -> bool:
        """Remove the adapter registered for *source*.

        Args:
            source: Source identifier.

        Returns:
            True if an adapter was removed, False if *source* was not registered.
        """
        try:
            del self._adapters[source]
        except KeyError:
            return False
        return True

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, source: str) -> DiscoveryAdapter | None:
        """Return the registered adapter for *source*, or None.

        Args:
            source: Source identifier.

        Returns:
            The registered adapter, or None if not found.
        """
        return self._adapters.get(source)

    def list_registered(self) -> list[tuple[str, DiscoveryAdapter]]:
        """Return all registered adapters in registration order.

        Returns:
            List of (source, adapter) tuples.
        """
        return list(self._adapters.items())

    def is_registered(self, source: str) -> bool:
        """Return True if an adapter is registered for *source*.

        Args:
            source: Source identifier.

        Returns:
            True if registered, False otherwise.
        """
        return source in self._adapters

    # ------------------------------------------------------------------
    # Internal validation
    # ------------------------------------------------------------------

    def _validate_adapter_contract(self, adapter: Any) -> None:
        """Validate that *adapter* satisfies the DiscoveryAdapter contract.

        Uses structural duck-typing because DiscoveryAdapter is a Protocol
        and may not be @runtime_checkable in all Python versions.

        Raises:
            TypeError: If the contract is not satisfied (missing attributes,
                       wrong types, or non-callable fetch).
            ValueError: If source or adapter_version are empty strings.
        """
        if not hasattr(adapter, "source"):
            raise TypeError(
                f"Object does not satisfy DiscoveryAdapter contract: "
                f"{type(adapter).__name__} missing 'source' attribute"
            )
        if not isinstance(adapter.source, str):
            raise TypeError(
                f"Object does not satisfy DiscoveryAdapter contract: "
                f"{type(adapter).__name__}.source must be a str"
            )
        if not adapter.source:
            raise ValueError("Adapter.source must not be empty")

        if not hasattr(adapter, "adapter_version"):
            raise TypeError(
                f"Object does not satisfy DiscoveryAdapter contract: "
                f"{type(adapter).__name__} missing 'adapter_version' attribute"
            )
        if not isinstance(adapter.adapter_version, str):
            raise TypeError(
                f"Object does not satisfy DiscoveryAdapter protocol: "
                f"{type(adapter).__name__}.adapter_version must be a str"
            )
        if not adapter.adapter_version:
            raise ValueError("Adapter.adapter_version must not be empty")

        if not callable(getattr(adapter, "fetch", None)):
            raise TypeError(
                f"Object does not satisfy DiscoveryAdapter contract: "
                f"{type(adapter).__name__} missing callable 'fetch' method"
            )
