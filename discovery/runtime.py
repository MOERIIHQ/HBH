"""
HBH Discovery Runtime — Phase 1b-GH-2C.

Source-agnostic discovery runtime/application service that bridges
configuration → adapter registry → discovery engine.

Responsibilities:
- Load discovery configuration
- Determine enabled sources in deterministic order
- Resolve enabled sources through AdapterRegistry
- Detect missing configured adapters and report them explicitly
- Build RunContext with per-source configuration
- Execute adapters through the existing DiscoveryEngine
- Aggregate and return discovery run results

Does NOT contain:
- Candidate validation (reuses DiscoveryEngine)
- Deduplication (reuses DiscoveryEngine)
- Persistence (reuses DiscoveryEngine)
- Raw evidence storage (reuses DiscoveryEngine + RawStorage)
- Global candidate caps (reuses DiscoveryEngine's MAX_TOTAL_CANDIDATES)
- Runtime limits (reuses DiscoveryEngine's MAX_RUN_DURATION_SECONDS)
- Any source-specific adapter logic
- Any network implementation
- Any scheduler, CLI, policy, or triage logic
"""

from __future__ import annotations

from dataclasses import dataclass

from hbh.core.audit import log_error, log_info
from hbh.core.config import Config
from hbh.discovery.config import DiscoveryConfig, SourceConfig, load_discovery_config
from hbh.discovery.engine import (
    DiscoveryEngine,
    DiscoveryRunResult,
    create_discovery_engine,
)
from hbh.discovery.models import (
    ADAPTER_CONTRACT_VERSION,
    AdapterResult,
    AdapterStatus,
    BountyCandidate,
    DiscoveryAdapter,
    RunContext,
    RunStatus,
)
from hbh.discovery.registry import AdapterRegistry


# ---------------------------------------------------------------------------
# Fake adapter factory (test helper only — production code is source-agnostic)
# ---------------------------------------------------------------------------


def make_fake_adapter(
    source: str,
    *,
    status: str = AdapterStatus.SUCCESS,
    candidates: list[BountyCandidate] | None = None,
    error: str | None = None,
    adapter_version: str = ADAPTER_CONTRACT_VERSION,
) -> DiscoveryAdapter:
    """Build a minimal in-memory fake adapter for tests.

    This is strictly a test helper. Production code defines real adapters
    elsewhere and never imports or uses this function.
    """

    class FakeAdapter:
        def __init__(self):
            self.source = source
            self.adapter_version = adapter_version

        def fetch(self, run_context: RunContext) -> AdapterResult:
            return AdapterResult(
                source=source,
                adapter_version=adapter_version,
                status=status,
                candidates=candidates or [],
                pages_fetched=0 if status == AdapterStatus.FAILED else 1,
                candidates_fetched=len(candidates or []),
                error=error,
                rate_limit_hit=False,
                elapsed_seconds=0.0,
            )

    return FakeAdapter()


# ---------------------------------------------------------------------------
# RuntimeMissingAdapter — explicit representation of a configured-but-missing adapter
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuntimeMissingAdapter:
    """A configured source that is enabled but has no registered adapter.

    This is not a BountyCandidate, an AdapterResult, or a state-machine state.
    It is a runtime diagnostic value used to make missing adapters observable.
    """

    source: str
    config: dict[str, str | list[str]] | None


# ---------------------------------------------------------------------------
# Discovery Runtime
# ---------------------------------------------------------------------------


@dataclass
class DiscoveryRuntime:
    """Source-agnostic discovery runtime.

    Responsibilities:
    - Load discovery configuration
    - Determine enabled sources in deterministic order (sorted by source name)
    - Resolve enabled sources through AdapterRegistry
    - Detect missing configured adapters and raise explicitly
    - Build RunContext carrying per-source configuration
    - Execute adapters through the existing DiscoveryEngine
    - Aggregate and return DiscoveryRunResult

    Does NOT contain:
    - Candidate validation — reuses DiscoveryEngine._validate_candidate
    - Deduplication — reuses DiscoveryEngine._process_single_candidate
    - Persistence — reuses DiscoveryEngine._persist_candidate
    - Raw evidence storage — reuses DiscoveryEngine.raw_storage
    - Global candidate caps — reuses DiscoveryEngine.MAX_TOTAL_CANDIDATES
    - Runtime limits — reuses DiscoveryEngine.MAX_RUN_DURATION_SECONDS
    - Any source-specific adapter logic
    - Any network implementation
    - Any scheduler, CLI, policy, or triage logic
    """

    registry: AdapterRegistry

    def __init__(self, registry: AdapterRegistry | None = None) -> None:
        self.registry = registry or AdapterRegistry()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        config: Config,
        *,
        trigger: str = "manual",
        engine: DiscoveryEngine | None = None,
    ) -> DiscoveryRunResult:
        """Run discovery for all enabled configured sources.

        Steps:
        1. Load discovery configuration
        2. Determine enabled sources in deterministic order
        3. Resolve enabled sources through AdapterRegistry
        4. Detect missing configured adapters → raise RuntimeError
        5. Build RunContext with per-source configuration
        6. Execute adapters through existing DiscoveryEngine
        7. Return DiscoveryRunResult
        """
        discovery_config = load_discovery_config(config)

        enabled_sources = self._collect_enabled_sources(discovery_config)
        adapter_results = self._resolve_and_check_missing(enabled_sources)

        if not adapter_results:
            # No enabled sources, or all disabled — nothing to run.
            return self._empty_run_result(trigger)

        # Delegate everything else to the existing DiscoveryEngine.
        eng = engine or create_discovery_engine(config=config)

        source_config = self._build_source_config(enabled_sources)

        return eng.run(
            adapters=adapter_results,
            discovery_query="runtime:multi-source",
            source_config=source_config,
            trigger=trigger,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _collect_enabled_sources(
        self, discovery_config: DiscoveryConfig
    ) -> list[SourceConfig]:
        """Collect enabled source configurations in deterministic order.

        Deterministic order = sorted by source name (lexicographic).
        """
        result: list[SourceConfig] = []
        for source_name in sorted(discovery_config.sources.keys()):
            src = discovery_config.get_source(source_name)
            if src is None:
                continue
            if not src.enabled:
                continue
            result.append(src)
        return result

    def _resolve_and_check_missing(
        self, enabled_sources: list[SourceConfig]
    ) -> list[DiscoveryAdapter]:
        """Resolve adapters for enabled sources.

        Raises RuntimeError if any enabled source has no registered adapter.
        """
        adapters: list[DiscoveryAdapter] = []
        missing: list[RuntimeMissingAdapter] = []

        for src in enabled_sources:
            adapter = self.registry.get(src.source)
            if adapter is None:
                missing.append(
                    RuntimeMissingAdapter(source=src.source, config=src.config)
                )
                log_error(
                    event="runtime_missing_adapter",
                    message=(
                        f"Enabled source {src.source!r} has no registered adapter"
                    ),
                    actor="discovery_runtime",
                    entity_id=src.source,
                    reason="missing_adapter",
                )
            else:
                adapters.append(adapter)

        if missing:
            first = missing[0]
            raise RuntimeError(
                f"Enabled source {first.source!r} has no registered adapter"
            )

        return adapters

    def _build_source_config(
        self, enabled_sources: list[SourceConfig]
    ) -> dict[str, dict[str, str | list[str]]]:
        """Build the per-source configuration dict for RunContext.

        Each adapter reads run_context.source_config[self.source].
        """
        result: dict[str, dict[str, str | list[str]] | None] = {}
        for src in enabled_sources:
            result[src.source] = src.config
        return result  # type: ignore[return-value]

    def _empty_run_result(self, trigger: str) -> DiscoveryRunResult:
        """Return a FAILED result when there are no enabled adapters to run."""
        return DiscoveryRunResult(
            run_id="",
            status=RunStatus.FAILED,
            started_at=None,
            finished_at=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat(),
            adapters_total=0,
            adapters_succeeded=0,
            adapters_failed=0,
            candidates_found=0,
            candidates_inserted=0,
            candidates_duplicate=0,
            duration_seconds=0.0,
            limit_reached=False,
            limit_reason="no_enabled_adapters",
        )
