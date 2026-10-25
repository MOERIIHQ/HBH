"""
HBH Discovery Engine Core — Phase 1b-GH-2A.

Source-agnostic discovery orchestrator.

Coordinates adapter execution, validates candidates, persists discoveries,
emits audit events. Does not know about any specific source.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from hbh.core.audit import AuditLogger, log_info, log_warn
from hbh.core.config import Config
from hbh.core.database import (
    Database,
    insert_discovery_run,
    update_discovery_run,
    insert_discovered_bounty,
    exists_source_source_id,
    get_discovery_run,
)
from hbh.core.state_machine import (
    BountyStatus,
    Transition,
    record_transition,
)
from hbh.discovery.models import (
    ADAPTER_CONTRACT_VERSION,
    AdapterResult,
    AdapterStatus,
    BountyCandidate,
    DiscoveryAdapter,
    RunContext,
    RunStatus,
    make_bounty_candidate,
    make_adapter_result,
    make_run_context,
)

# ---------------------------------------------------------------------------
# Hard limits (absolute engine ceilings)
# ---------------------------------------------------------------------------

MAX_TOTAL_CANDIDATES: int = 200
MAX_RUN_DURATION_SECONDS: int = 300

# ---------------------------------------------------------------------------
# Ingestion outcome types (not state machine states)
# ---------------------------------------------------------------------------

class IngestionOutcome:
    """
    Non-state-machine outcomes for candidate processing.
    These represent what happened to a candidate during ingestion.
    """

    DISCOVERED = "DISCOVERED"
    REJECTED = "DISCOVERY_REJECTED"
    DUPLICATE = "DISCOVERY_DUPLICATE"


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ValidationResult:
    """Result of minimal structural validation on a candidate."""

    valid: bool
    reason: str | None = None
    field: str | None = None

    @classmethod
    def ok(cls) -> ValidationResult:
        return cls(valid=True)

    @classmethod
    def invalid(cls, reason: str, field: str | None = None) -> ValidationResult:
        return cls(valid=False, reason=reason, field=field)


# ---------------------------------------------------------------------------
# DiscoveryEngine
# ---------------------------------------------------------------------------

@dataclass
class DiscoveryEngine:
    """
    Source-agnostic discovery orchestrator.

    Responsibilities:
    - Create and track discovery runs
    - Execute adapters in isolation
    - Validate candidates minimally
    - Persist discoveries via the database layer
    - Emit audit events
    - Enforce hard limits
    - Compute final run status

    Does NOT know about any specific source.
    """

    config: Config
    db: Database
    logger: AuditLogger

    # Runtime state (set during run)
    _run_id: str | None = None
    _started_at: datetime | None = None
    _total_candidates_found: int = 0
    _total_candidates_inserted: int = 0
    _total_duplicates: int = 0
    _adapters_total: int = 0
    _adapters_succeeded: int = 0
    _adapters_failed: int = 0
    _limit_reached: bool = False
    _limit_reason: str | None = None

    # ------------------------------------------------------------------
    # Raw evidence storage (GH-2B)
    # ------------------------------------------------------------------
    raw_storage: RawStorage | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        *,
        adapters: list[DiscoveryAdapter],
        discovery_query: str = "",
        source_config: dict[str, Any] | None = None,
        trigger: str = "manual",
    ) -> DiscoveryRunResult:
        """
        Execute a discovery run with the given adapters.

        Args:
            adapters: List of DiscoveryAdapter instances to execute.
            discovery_query: Source-specific query string.
            source_config: Source configuration dict.
            trigger: What triggered this run ('manual', 'scheduled', etc.).

        Returns:
            DiscoveryRunResult with the final run state and statistics.
        """
        self._run_id = self._generate_run_id()
        self._started_at = datetime.now(timezone.utc)
        self._total_candidates_found = 0
        self._total_candidates_inserted = 0
        self._total_duplicates = 0
        self._adapters_total = len(adapters)
        self._adapters_succeeded = 0
        self._adapters_failed = 0
        self._limit_reached = False
        self._limit_reason = None

        run_context = RunContext(
            run_id=self._run_id,
            started_at=self._started_at,
            discovery_query=discovery_query or f"discovery:{self._run_id}",
            source_config=source_config or {},
        )

        # 1. Create the discovery run record
        self._create_run(trigger)

        # 2. Execute adapters
        adapter_results: list[AdapterResult] = []
        for adapter in adapters:
            if self._limit_reached:
                break
            try:
                result = self._execute_adapter(adapter, run_context)
                adapter_results.append(result)
            except Exception as e:
                self._adapters_failed += 1
                self._log_adapter_error(adapter, e)
                adapter_results.append(
                    make_adapter_result(
                        source=adapter.source,
                        status=AdapterStatus.FAILED,
                        error=f"Adapter raised exception: {type(e).__name__}",
                    )
                )

        # 3. Finalize
        return self._finalize(adapter_results)

    # ------------------------------------------------------------------
    # Internal: run lifecycle
    # ------------------------------------------------------------------

    def _generate_run_id(self) -> str:
        """Generate a unique run ID."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        import uuid
        return f"discovery-{ts}-{uuid.uuid4().hex[:8]}"

    def _create_run(self, trigger: str) -> None:
        """Create the discovery run record in the database."""
        now = self._started_at.isoformat()
        insert_discovery_run(
            self.db,
            run_id=self._run_id,
            started_at=now,
            trigger=trigger,
        )
        self.logger.transition(
            entity_id=self._run_id,
            actor="discovery_engine",
            from_state="none",
            to_state=RunStatus.RUNNING,
            reason="discovery_run_started",
            metadata={"trigger": trigger, "adapters_total": self._adapters_total},
        )
        log_info(
            event="discovery_run_started",
            message=f"Discovery run {self._run_id} started",
            actor="discovery_engine",
            entity_id=self._run_id,
        )

    def _finalize(self, adapter_results: list[AdapterResult]) -> DiscoveryRunResult:
        """Compute final status and persist run completion."""
        now = datetime.now(timezone.utc).isoformat()
        duration = (datetime.now(timezone.utc) - self._started_at).total_seconds() if self._started_at else 0.0

        # Determine final status
        final_status = self._compute_final_status(adapter_results)

        # Check duration limit
        if duration > MAX_RUN_DURATION_SECONDS:
            if self._total_candidates_inserted > 0:
                final_status = RunStatus.PARTIAL
            else:
                final_status = RunStatus.FAILED
            self._limit_reached = True
            self._limit_reason = "max_run_duration_seconds_exceeded"

        # Update the run record
        update_discovery_run(
            self.db,
            run_id=self._run_id,
            finished_at=now,
            status=final_status,
            adapters_total=self._adapters_total,
            adapters_succeeded=self._adapters_succeeded,
            adapters_failed=self._adapters_failed,
            candidates_found=self._total_candidates_found,
            candidates_inserted=self._total_candidates_inserted,
            candidates_duplicate=self._total_duplicates,
            error_summary=self._limit_reason or "",
        )

        # Audit event
        self.logger.transition(
            entity_id=self._run_id,
            actor="discovery_engine",
            from_state=RunStatus.RUNNING,
            to_state=final_status,
            reason="discovery_run_completed",
            metadata={
                "adapters_total": self._adapters_total,
                "adapters_succeeded": self._adapters_succeeded,
                "adapters_failed": self._adapters_failed,
                "candidates_found": self._total_candidates_found,
                "candidates_inserted": self._total_candidates_inserted,
                "candidates_duplicate": self._total_duplicates,
                "duration_seconds": round(duration, 2),
                "limit_reached": self._limit_reached,
                "limit_reason": self._limit_reason,
            },
        )

        return DiscoveryRunResult(
            run_id=self._run_id,
            status=final_status,
            started_at=self._started_at.isoformat() if self._started_at else None,
            finished_at=now,
            adapters_total=self._adapters_total,
            adapters_succeeded=self._adapters_succeeded,
            adapters_failed=self._adapters_failed,
            candidates_found=self._total_candidates_found,
            candidates_inserted=self._total_candidates_inserted,
            candidates_duplicate=self._total_duplicates,
            duration_seconds=round(duration, 2),
            limit_reached=self._limit_reached,
            limit_reason=self._limit_reason,
        )

    def _compute_final_status(self, adapter_results: list[AdapterResult]) -> str:
        """
        Compute the final run status based on adapter results.

        SUCCESS: all adapters succeeded (even with 0 candidates)
        PARTIAL: some succeeded, some failed
        FAILED: all failed
        """
        if not adapter_results:
            return RunStatus.FAILED

        any_succeeded = any(
            r.status == AdapterStatus.SUCCESS or r.status == AdapterStatus.PARTIAL
            for r in adapter_results
        )
        any_failed = any(r.status == AdapterStatus.FAILED for r in adapter_results)

        if any_succeeded and any_failed:
            return RunStatus.PARTIAL
        elif any_succeeded:
            return RunStatus.SUCCESS
        else:
            return RunStatus.FAILED

    # ------------------------------------------------------------------
    # Internal: adapter execution
    # ------------------------------------------------------------------

    def _execute_adapter(self, adapter: DiscoveryAdapter, run_context: RunContext) -> AdapterResult:
        """Execute a single adapter and process its results."""
        start = time.monotonic()
        try:
            result = adapter.fetch(run_context)
        except Exception as e:
            self._adapters_failed += 1
            elapsed = time.monotonic() - start
            return AdapterResult(
                source=adapter.source,
                adapter_version=adapter.adapter_version,
                status=AdapterStatus.FAILED,
                candidates=[],
                pages_fetched=0,
                candidates_fetched=0,
                error=f"Adapter exception: {type(e).__name__}: {e}",
                rate_limit_hit=False,
                elapsed_seconds=elapsed,
            )

        elapsed = time.monotonic() - start
        result = AdapterResult(
            source=result.source,
            adapter_version=result.adapter_version,
            status=result.status,
            candidates=result.candidates,
            pages_fetched=result.pages_fetched,
            candidates_fetched=result.candidates_fetched,
            error=result.error,
            rate_limit_hit=result.rate_limit_hit,
            elapsed_seconds=elapsed,
        )

        # Track adapter outcome
        if result.status == AdapterStatus.FAILED:
            self._adapters_failed += 1
        else:
            self._adapters_succeeded += 1

        # Process candidates from successful/partial adapters
        if result.status in (AdapterStatus.SUCCESS, AdapterStatus.PARTIAL):
            self._process_candidates(result.candidates)

        return result

    def _log_adapter_error(self, adapter: DiscoveryAdapter, exc: Exception) -> None:
        """Log an adapter execution error."""
        log_warn(
            event="adapter_execution_error",
            message=f"Adapter {adapter.source} raised exception",
            actor="discovery_engine",
            entity_id=self._run_id,
            reason=f"{type(exc).__name__}: {exc}",
        )

    # ------------------------------------------------------------------
    # Internal: candidate processing
    # ------------------------------------------------------------------

    def _process_candidates(self, candidates: list[BountyCandidate]) -> None:
        """Process a list of candidates from an adapter result."""
        for candidate in candidates:
            if self._limit_reached:
                break
            self._total_candidates_found += 1
            self._process_single_candidate(candidate)

    def _process_single_candidate(self, candidate: BountyCandidate) -> None:
        """
        Process a single candidate: validate, check dedup, persist.

        On success: persists as DISCOVERED
        On validation failure: logs DISCOVERY_REJECTED
        On duplicate: logs DISCOVERY_DUPLICATE
        """
        # 1. Validate
        validation = self._validate_candidate(candidate)
        if not validation.valid:
            self._record_rejection(candidate, validation)
            return

        # 2. Check duplicate
        if exists_source_source_id(self.db, candidate.source, candidate.source_id):
            self._total_duplicates += 1
            self._record_duplicate(candidate)
            return

        # 3. Check total limit
        if self._total_candidates_inserted >= MAX_TOTAL_CANDIDATES:
            self._limit_reached = True
            self._limit_reason = "max_total_candidates_reached"
            self.logger.transition(
                entity_id=self._run_id,
                actor="discovery_engine",
                from_state=RunStatus.RUNNING,
                to_state=RunStatus.RUNNING,
                reason="max_total_candidates_reached",
                metadata={"candidates_inserted": self._total_candidates_inserted},
            )
            return

        # 4. Persist
        if self._persist_candidate(candidate):
            self._total_candidates_inserted += 1

    def _validate_candidate(self, candidate: BountyCandidate) -> ValidationResult:
        """
        Perform minimal structural validation on a candidate.

        Required identity:
        - source (non-empty)
        - source_id (non-empty)
        - discovery_run_id (non-empty)
        - adapter_version (non-empty)
        - raw_payload_reference (non-empty)
        - raw_payload_hash (non-empty)

        Basic content:
        - title (non-empty)
        - issue_url or repository_url (valid URL)
        """
        # Required identity fields (adapter-provided input)
        if not candidate.source:
            return ValidationResult.invalid("missing_source", "source")
        if not candidate.source_id:
            return ValidationResult.invalid("missing_source_id", "source_id")
        if not candidate.discovery_run_id:
            return ValidationResult.invalid("missing_discovery_run_id", "discovery_run_id")
        if not candidate.adapter_version:
            return ValidationResult.invalid("missing_adapter_version", "adapter_version")

        # Basic content
        if not candidate.title:
            return ValidationResult.invalid("missing_title", "title")

        # URL validation: at least one of issue_url or repository_url must be present and valid.
        # Treat None, empty string, whitespace-only, and the literal "None" as missing.
        def _url_missing(u: str | None) -> bool:
            if not isinstance(u, str):
                return True
            if u.strip() == "" or u.strip().lower() == "none":
                return True
            return False

        issue_missing = _url_missing(candidate.issue_url)
        repo_missing = _url_missing(candidate.repository_url)

        if issue_missing and repo_missing:
            return ValidationResult.invalid("missing_required_url", "issue_url")

        url_to_check = candidate.issue_url if not issue_missing else candidate.repository_url
        if not self._is_valid_url(url_to_check):
            return ValidationResult.invalid("invalid_url", "issue_url" if not issue_missing else "repository_url")

        return ValidationResult.ok()

    def _is_valid_url(self, url: str) -> bool:
        """Basic URL structure validation."""
        if not url or not isinstance(url, str):
            return False
        if "://" not in url:
            return False
        parts = url.split("://", 1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            return False
        scheme = parts[0].lower()
        if scheme not in ("http", "https"):
            return False
        if not parts[1].strip():
            return False
        return True

    def _persist_candidate(self, candidate: BountyCandidate) -> bool:
        """
        Persist a validated, non-duplicate candidate.

        Stores the raw source payload as an immutable evidence artifact
        (when raw_storage is configured), then persists the candidate record
        to SQLite.

        When raw_storage is configured, raw evidence is REQUIRED. If the
        raw payload is missing or storage fails, the candidate is rejected
        and NOT persisted — the system fails closed regarding provenance.

        Returns:
            True if the candidate was successfully persisted to SQLite.
            False if rejected (missing raw payload or storage failure).
        """
        # --- store raw evidence ------------------------------------------------
        raw_ref: str | None = None
        raw_hash: str | None = None

        if self.raw_storage is not None:
            # Raw evidence is required when storage is configured.
            if candidate.raw_payload is None:
                self._record_rejection(
                    candidate,
                    ValidationResult.invalid(
                        "raw_payload_required_but_missing", "raw_payload"
                    ),
                )
                return False
            try:
                raw_ref, raw_hash = self.raw_storage.store(
                    candidate.source, candidate.raw_payload
                )
            except Exception as exc:
                log_warn(
                    event="raw_evidence_store_failed",
                    message=(
                        f"Raw evidence store failed for "
                        f"{candidate.source}:{candidate.source_id}"
                    ),
                    actor="discovery_engine",
                    entity_id=self._run_id,
                    reason=f"{type(exc).__name__}: {exc}",
                )
                # Storage write failed — fail closed, do not persist.
                return False

        # --- insert into SQLite ------------------------------------------------
        insert_discovered_bounty(
            self.db,
            id=f"{candidate.source}:{candidate.source_id}",
            source=candidate.source,
            source_id=candidate.source_id,
            canonical_issue_key=candidate.canonical_issue_key,
            title=candidate.title,
            description=candidate.description,
            repository_url=candidate.repository_url,
            issue_url=candidate.issue_url,
            reward=candidate.reward,
            currency=candidate.currency,
            source_created_at=candidate.source_created_at,
            source_updated_at=candidate.source_updated_at,
            last_activity=candidate.last_activity,
            state=candidate.state,
            labels=json.dumps(candidate.labels) if candidate.labels else None,
            raw_payload_reference=raw_ref,
            raw_payload_hash=raw_hash,
            adapter_version=candidate.adapter_version,
            discovery_run_id=candidate.discovery_run_id,
            status=BountyStatus.DISCOVERED.value,
        )

        self.logger.transition(
            entity_id=f"{candidate.source}:{candidate.source_id}",
            actor="discovery_engine",
            from_state="none",
            to_state=BountyStatus.DISCOVERED.value,
            reason="discovery_ingested",
            metadata={
                "source": candidate.source,
                "source_id": candidate.source_id,
                "discovery_run_id": candidate.discovery_run_id,
                "adapter_version": candidate.adapter_version,
            },
        )
        return True

    def _record_rejection(self, candidate: BountyCandidate, validation: ValidationResult) -> None:
        """Record a validation rejection event."""
        self.logger.transition(
            entity_id=f"{candidate.source}:{candidate.source_id}",
            actor="discovery_engine",
            from_state="none",
            to_state="none",
            reason="discovery_rejected",
            metadata={
                "source": candidate.source,
                "source_id": candidate.source_id,
                "discovery_run_id": candidate.discovery_run_id,
                "rejection_reason": validation.reason,
                "rejection_field": validation.field,
            },
        )

    def _record_duplicate(self, candidate: BountyCandidate) -> None:
        """Record a duplicate detection event."""
        self.logger.transition(
            entity_id=f"{candidate.source}:{candidate.source_id}",
            actor="discovery_engine",
            from_state="none",
            to_state="none",
            reason="discovery_duplicate",
            metadata={
                "source": candidate.source,
                "source_id": candidate.source_id,
                "discovery_run_id": candidate.discovery_run_id,
            },
        )


# ---------------------------------------------------------------------------
# DiscoveryRunResult
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DiscoveryRunResult:
    """
    Result of a completed discovery run.

    Immutable snapshot of the run's final state.
    """

    run_id: str
    status: str
    started_at: str | None
    finished_at: str
    adapters_total: int
    adapters_succeeded: int
    adapters_failed: int
    candidates_found: int
    candidates_inserted: int
    candidates_duplicate: int
    duration_seconds: float
    limit_reached: bool
    limit_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "run_id": self.run_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "adapters_total": self.adapters_total,
            "adapters_succeeded": self.adapters_succeeded,
            "adapters_failed": self.adapters_failed,
            "candidates_found": self.candidates_found,
            "candidates_inserted": self.candidates_inserted,
            "candidates_duplicate": self.candidates_duplicate,
            "duration_seconds": self.duration_seconds,
            "limit_reached": self.limit_reached,
            "limit_reason": self.limit_reason,
        }


# ---------------------------------------------------------------------------
# Convenience: create engine
# ---------------------------------------------------------------------------

def create_discovery_engine(config: Config, db: Database | None = None) -> DiscoveryEngine:
    """
    Create a DiscoveryEngine instance.

    Args:
        config: HBH Config instance.
        db: Optional Database instance. If None, creates one from config.

    Returns:
        DiscoveryEngine ready to run discovery.
    """
    if db is None:
        from hbh.core.database import Database as DB, ensure_schema
        db = DB.create(config)
        ensure_schema(db)

    logger = AuditLogger(config, db=db)
    raw_storage = None
    if config.raw_storage_path:
        from hbh.discovery.raw_storage import RawStorage
        raw_storage = RawStorage(config.raw_storage_path)

    return DiscoveryEngine(config=config, db=db, logger=logger, raw_storage=raw_storage)


# ---------------------------------------------------------------------------
# Module re-exports
# ---------------------------------------------------------------------------

__all__ = [
    "DiscoveryEngine",
    "DiscoveryRunResult",
    "IngestionOutcome",
    "MAX_TOTAL_CANDIDATES",
    "MAX_RUN_DURATION_SECONDS",
    "create_discovery_engine",
    "ValidationResult",
]
