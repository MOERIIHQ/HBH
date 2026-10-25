# HBH Discovery — Phase 1b-GH-1 foundation contracts.

# Source-neutral dataclasses and protocol for discovery adapters.

# Re-export the public contract symbols from the models and config submodules.

from hbh.discovery.models import (
    ADAPTER_CONTRACT_VERSION,
    BountyCandidate,
    RunContext,
    AdapterResult,
    AdapterStatus,
    RunStatus,
    DiscoveryAdapter,
)

from hbh.discovery.config import (
    load_discovery_config,
)

from hbh.discovery.engine import (
    DiscoveryEngine,
    DiscoveryRunResult,
    IngestionOutcome,
    MAX_TOTAL_CANDIDATES,
    MAX_RUN_DURATION_SECONDS,
    ValidationResult,
    create_discovery_engine,
)

from hbh.discovery.registry import AdapterRegistry

from hbh.discovery.runtime import (
    DiscoveryRuntime,
    RuntimeMissingAdapter,
    make_fake_adapter,
)

__all__ = [
    "ADAPTER_CONTRACT_VERSION",
    "BountyCandidate",
    "RunContext",
    "AdapterResult",
    "AdapterStatus",
    "RunStatus",
    "DiscoveryAdapter",
    "load_discovery_config",
    "DiscoveryEngine",
    "DiscoveryRunResult",
    "IngestionOutcome",
    "MAX_TOTAL_CANDIDATES",
    "MAX_RUN_DURATION_SECONDS",
    "ValidationResult",
    "create_discovery_engine",
    "AdapterRegistry",
    "DiscoveryRuntime",
    "RuntimeMissingAdapter",
    "make_fake_adapter",
]
