"""
HBH Discovery Contracts.

Source-neutral dataclasses and protocol for discovery adapters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol, TypedDict


# ---------------------------------------------------------------------------
# Contract version
# ---------------------------------------------------------------------------

ADAPTER_CONTRACT_VERSION: str = "1.0.0"
"""Version of the discovery adapter contract. Bumped when the contract shape changes."""


# ---------------------------------------------------------------------------
# RunContext — what the engine passes to an adapter
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RunContext:
    """Context passed to a DiscoveryAdapter.fetch() call.

    Frozen: the adapter must not mutate this.
    """

    run_id: str
    """Unique identifier for this discovery run."""

    started_at: datetime
    """Timestamp when the run started."""

    discovery_query: str
    """Source-specific query string for this run, e.g. 'github:owner/repo'."""

    source_config: dict[str, Any]
    """Source configuration dict from discovery_config.yaml.

    The adapter extracts what it needs from this dict.
    The keys and shape are source-specific; the engine does not interpret them.
    """

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id must not be empty")
        if not self.started_at:
            raise ValueError("started_at must not be empty")
        if not self.discovery_query:
            raise ValueError("discovery_query must not be empty")


# ---------------------------------------------------------------------------
# BountyCandidate — normalized discovery output
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BountyCandidate:
    """A single discovered bounty candidate, normalized to the common contract.

    All fields are immutable after construction.
    Source-specific raw data is preserved via raw_payload_reference and
    raw_payload_hash; the engine stores the actual raw payload separately.
    """

    source: str
    """Source identifier, e.g. 'github'. Lowercase, no spaces."""

    source_id: str
    """Primary identity within the source. Unique per source."""

    discovery_run_id: str
    """Discovery run that produced this candidate. Links candidate to its run."""

    canonical_issue_key: str | None = None
    """Human-readable canonical key, e.g. 'owner/repo#123'.

    Not used as the primary identity. Optional but recommended for display.
    """

    title: str | None = None
    """Candidate title / subject line."""

    description: str | None = None
    """Candidate description / body text."""

    repository_url: str | None = None
    """URL of the repository containing the candidate."""

    issue_url: str | None = None
    """Direct URL to the candidate (issue, post, etc.)."""

    reward: str | None = None
    """Reward amount as a string, e.g. '500'.

    NULL when the source has no bounty/reward field.
    The adapter must NOT infer reward from labels, text, or comments.
    """

    currency: str | None = None
    """Reward currency code, e.g. 'USD'.

    NULL when reward is NULL or currency is unknown.
    """

    source_created_at: str | None = None
    """ISO-8601 timestamp of when the candidate was created in the source."""

    source_updated_at: str | None = None
    """ISO-8601 timestamp of when the candidate was last updated in the source."""

    last_activity: str | None = None
    """ISO-8601 timestamp of the most recent activity (comment, update, etc.)."""

    state: str | None = None
    """Source-native state, e.g. 'open', 'closed', 'merged'."""

    labels: list[str] = field(default_factory=list)
    """List of label/tag strings attached to the candidate.

    Empty list when no labels. Not used for filtering in v0.1.
    """

    raw_payload_reference: str | None = None
    """Reference to the raw evidence stored by the engine.

    Set by the engine after persistence, not by the adapter.
    The adapter returns the raw data; the engine stores it and sets this.
    """

    raw_payload_hash: str | None = None
    """Hash of the raw response payload for integrity verification.

    Set by the engine after persistence.
    """

    raw_payload: dict[str, Any] | None = None
    """Raw source payload from the discovery adapter, stored as evidence.

    Populated by the adapter with the actual source response data.
    Consumed by the engine for raw evidence storage; NOT persisted to SQLite.
    Source-agnostic: a generic dict carrying the adapter's raw output.
    """

    adapter_version: str = ADAPTER_CONTRACT_VERSION
    """Version of the adapter that produced this candidate."""

    def __post_init__(self) -> None:
        if not self.source:
            raise ValueError("source must not be empty")
        if not self.source_id:
            raise ValueError("source_id must not be empty")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for storage / JSON serialization."""
        return {
            "source": self.source,
            "source_id": self.source_id,
            "canonical_issue_key": self.canonical_issue_key,
            "title": self.title,
            "description": self.description,
            "repository_url": self.repository_url,
            "issue_url": self.issue_url,
            "reward": self.reward,
            "currency": self.currency,
            "source_created_at": self.source_created_at,
            "source_updated_at": self.source_updated_at,
            "last_activity": self.last_activity,
            "state": self.state,
            "labels": self.labels,
            "raw_payload_reference": self.raw_payload_reference,
            "raw_payload_hash": self.raw_payload_hash,
            "adapter_version": self.adapter_version,
            "discovery_run_id": self.discovery_run_id,
        }


# ---------------------------------------------------------------------------
# AdapterResult — what the adapter returns
# ---------------------------------------------------------------------------

class AdapterStatus(str):
    """Literal values for adapter result status."""

    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class RunStatus(str):
    """Valid status values for a discovery run.

    These map directly to the ``status`` column of ``discovery_runs``.
    """

    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"

    @classmethod
    def is_valid(cls, value: str) -> bool:
        """Return True if *value* is a known RunStatus."""
        return value in (cls.RUNNING, cls.SUCCESS, cls.PARTIAL, cls.FAILED)


@dataclass(frozen=True)
class AdapterResult:
    """Result of a single adapter fetch call.

    Frozen: the engine must not mutate this after construction.
    """

    source: str
    """Source identifier, matching the adapter's source."""

    adapter_version: str
    """Version of the adapter that produced this result."""

    status: str
    """One of: SUCCESS, PARTIAL, FAILED.

    SUCCESS — all candidates fetched, no errors.
    PARTIAL — some candidates fetched, non-fatal issues occurred.
    FAILED — adapter could not produce any candidates.
    """

    candidates: list[BountyCandidate]
    """List of normalized candidates. Empty when status is FAILED."""

    pages_fetched: int
    """Number of pages actually fetched from the source."""

    candidates_fetched: int
    """Number of raw candidates fetched before normalization/dedup."""

    error: str | None = None
    """Human-readable error summary. NULL when status is SUCCESS."""

    rate_limit_hit: bool = False
    """True when the adapter hit a rate limit during this fetch."""

    elapsed_seconds: float = 0.0
    """Wall-clock time for the fetch, in seconds."""

    def __post_init__(self) -> None:
        if not self.source:
            raise ValueError("source must not be empty")
        if self.status not in (AdapterStatus.SUCCESS, AdapterStatus.PARTIAL, AdapterStatus.FAILED):
            raise ValueError(
                f"status must be one of {AdapterStatus.SUCCESS}, {AdapterStatus.PARTIAL}, "
                f"{AdapterStatus.FAILED}; got {self.status!r}"
            )
        if self.status == AdapterStatus.FAILED and self.candidates:
            raise ValueError("FAILED result must have empty candidates")
        if self.pages_fetched < 0:
            raise ValueError("pages_fetched must be >= 0")
        if self.candidates_fetched < 0:
            raise ValueError("candidates_fetched must be >= 0")
        if self.elapsed_seconds < 0:
            raise ValueError("elapsed_seconds must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "source": self.source,
            "adapter_version": self.adapter_version,
            "status": self.status,
            "candidates": [c.to_dict() for c in self.candidates],
            "pages_fetched": self.pages_fetched,
            "candidates_fetched": self.candidates_fetched,
            "error": self.error,
            "rate_limit_hit": self.rate_limit_hit,
            "elapsed_seconds": self.elapsed_seconds,
        }


# ---------------------------------------------------------------------------
# DiscoveryAdapter — the adapter protocol
# ---------------------------------------------------------------------------

class DiscoveryAdapter(Protocol):
    """Protocol for discovery adapters.

    An adapter fetches candidates from a single source and returns them
    normalized as BountyCandidate instances wrapped in an AdapterResult.

    The adapter does NOT persist to SQLite. Persistence is the engine's
    responsibility.
    """

    source: str
    """Source identifier, e.g. 'github'. Must match what is returned in results."""

    adapter_version: str
    """Version string for this adapter implementation."""

    def fetch(self, run_context: RunContext) -> AdapterResult:
        """Fetch candidates from the source.

        Args:
            run_context: Context for this run, including config, limits, and run_id.

        Returns:
            AdapterResult with normalized candidates, status, and metadata.
        """
        ...  # pragma: no cover


# ---------------------------------------------------------------------------
# Convenience constructors for tests
# ---------------------------------------------------------------------------

def make_run_context(
    run_id: str = "test-run-001",
    *,
    discovery_query: str = "github:owner/repo",
    source_config: dict[str, Any] | None = None,
) -> RunContext:
    """Construct a RunContext for testing."""
    started_at = datetime.now(timezone.utc)
    return RunContext(
        run_id=run_id,
        started_at=started_at,
        discovery_query=discovery_query,
        source_config=source_config or {"repositories": []},
    )


def make_bounty_candidate(
    source: str = "github",
    source_id: str = "123",
    *,
    title: str = "Test issue",
    description: str = "Test description",
    repository_url: str = "https://github.com/owner/repo",
    issue_url: str = "https://github.com/owner/repo/issues/123",
    source_created_at: str | None = None,
    source_updated_at: str | None = None,
    labels: list[str] | None = None,
    reward: str | None = None,
    currency: str | None = None,
    discovery_run_id: str = "run-001",
) -> BountyCandidate:
    """Construct a BountyCandidate for testing."""
    now = datetime.now(timezone.utc).isoformat()
    return BountyCandidate(
        source=source,
        source_id=source_id,
        discovery_run_id=discovery_run_id,
        canonical_issue_key=f"owner/repo#{source_id}",
        title=title,
        description=description,
        repository_url=repository_url,
        issue_url=issue_url,
        reward=reward,
        currency=currency,
        source_created_at=source_created_at or now,
        source_updated_at=source_updated_at or now,
        last_activity=source_updated_at or now,
        state="open",
        labels=labels or [],
        adapter_version=ADAPTER_CONTRACT_VERSION,
        raw_payload_reference=f"{source}/abc123.json",
        raw_payload_hash="abc123",
    )


def make_adapter_result(
    source: str = "github",
    *,
    status: str = AdapterStatus.SUCCESS,
    candidates: list[BountyCandidate] | None = None,
    pages_fetched: int = 1,
    candidates_fetched: int = 1,
    error: str | None = None,
    rate_limit_hit: bool = False,
    elapsed_seconds: float = 0.5,
) -> AdapterResult:
    """Construct an AdapterResult for testing."""
    return AdapterResult(
        source=source,
        adapter_version=ADAPTER_CONTRACT_VERSION,
        status=status,
        candidates=candidates or [],
        pages_fetched=pages_fetched,
        candidates_fetched=candidates_fetched,
        error=error,
        rate_limit_hit=rate_limit_hit,
        elapsed_seconds=elapsed_seconds,
    )
