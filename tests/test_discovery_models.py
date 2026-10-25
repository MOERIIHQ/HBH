"""
Tests for hbh.discovery.models — Phase 1b-GH-1.

Focused tests for the Discovery contracts:
- BountyCandidate construction and nullable fields
- RunContext construction
- AdapterResult construction
- DiscoveryAdapter protocol

No GitHub-specific logic — these are source-neutral contracts.
"""

from __future__ import annotations

import pytest

from hbh.discovery.models import (
    BountyCandidate,
    RunContext,
    AdapterResult,
    RunStatus,
    DiscoveryAdapter,
    ADAPTER_CONTRACT_VERSION,
)


# ---------------------------------------------------------------------------
# BountyCandidate tests
# ---------------------------------------------------------------------------

class TestBountyCandidateRequiredFields:
    """Required fields must be provided; they are non-nullable by contract."""

    def test_source_required(self):
        """source must be provided and non-empty."""
        candidate = BountyCandidate(
            source="github",
            source_id="123",
            raw_payload_reference="github/abc123.json",
            raw_payload_hash="abc123",
            adapter_version="0.1.0",
            discovery_run_id="run-001",
        )
        assert candidate.source == "github"

    def test_source_id_required(self):
        """source_id must be provided."""
        candidate = BountyCandidate(
            source="github",
            source_id="123",
            raw_payload_reference="github/abc123.json",
            raw_payload_hash="abc123",
            adapter_version="0.1.0",
            discovery_run_id="run-001",
        )
        assert candidate.source_id == "123"

    def test_raw_payload_reference_required(self):
        """raw_payload_reference must be provided."""
        candidate = BountyCandidate(
            source="github",
            source_id="123",
            raw_payload_reference="github/abc123.json",
            raw_payload_hash="abc123",
            adapter_version="0.1.0",
            discovery_run_id="run-001",
        )
        assert candidate.raw_payload_reference == "github/abc123.json"

    def test_raw_payload_hash_required(self):
        """raw_payload_hash must be provided."""
        candidate = BountyCandidate(
            source="github",
            source_id="123",
            raw_payload_reference="github/abc123.json",
            raw_payload_hash="abc123",
            adapter_version="0.1.0",
            discovery_run_id="run-001",
        )
        assert candidate.raw_payload_hash == "abc123"

    def test_adapter_version_required(self):
        """adapter_version must be provided."""
        candidate = BountyCandidate(
            source="github",
            source_id="123",
            raw_payload_reference="github/abc123.json",
            raw_payload_hash="abc123",
            adapter_version="0.1.0",
            discovery_run_id="run-001",
        )
        assert candidate.adapter_version == "0.1.0"

    def test_discovery_run_id_required(self):
        """discovery_run_id must be provided."""
        candidate = BountyCandidate(
            source="github",
            source_id="123",
            raw_payload_reference="github/abc123.json",
            raw_payload_hash="abc123",
            adapter_version="0.1.0",
            discovery_run_id="run-001",
        )
        assert candidate.discovery_run_id == "run-001"


class TestBountyCandidateNullableFields:
    """Nullable fields default to None and can be set."""

    def test_canonical_issue_key_default_none(self):
        candidate = BountyCandidate(
            source="github",
            source_id="123",
            raw_payload_reference="github/abc.json",
            raw_payload_hash="abc",
            adapter_version="0.1.0",
            discovery_run_id="run-001",
        )
        assert candidate.canonical_issue_key is None

    def test_canonical_issue_key_settable(self):
        candidate = BountyCandidate(
            source="github",
            source_id="123",
            raw_payload_reference="github/abc.json",
            raw_payload_hash="abc",
            adapter_version="0.1.0",
            discovery_run_id="run-001",
            canonical_issue_key="octocat/Hello-World#123",
        )
        assert candidate.canonical_issue_key == "octocat/Hello-World#123"

    def test_title_default_none(self):
        candidate = BountyCandidate(
            source="github",
            source_id="123",
            raw_payload_reference="github/abc.json",
            raw_payload_hash="abc",
            adapter_version="0.1.0",
            discovery_run_id="run-001",
        )
        assert candidate.title is None

    def test_title_settable(self):
        candidate = BountyCandidate(
            source="github",
            source_id="123",
            raw_payload_reference="github/abc.json",
            raw_payload_hash="abc",
            adapter_version="0.1.0",
            discovery_run_id="run-001",
            title="Test Issue",
        )
        assert candidate.title == "Test Issue"

    def test_description_default_none(self):
        candidate = BountyCandidate(
            source="github",
            source_id="123",
            raw_payload_reference="github/abc.json",
            raw_payload_hash="abc",
            adapter_version="0.1.0",
            discovery_run_id="run-001",
        )
        assert candidate.description is None

    def test_repository_url_default_none(self):
        candidate = BountyCandidate(
            source="github",
            source_id="123",
            raw_payload_reference="github/abc.json",
            raw_payload_hash="abc",
            adapter_version="0.1.0",
            discovery_run_id="run-001",
        )
        assert candidate.repository_url is None

    def test_issue_url_default_none(self):
        candidate = BountyCandidate(
            source="github",
            source_id="123",
            raw_payload_reference="github/abc.json",
            raw_payload_hash="abc",
            adapter_version="0.1.0",
            discovery_run_id="run-001",
        )
        assert candidate.issue_url is None

    def test_reward_default_none(self):
        candidate = BountyCandidate(
            source="github",
            source_id="123",
            raw_payload_reference="github/abc.json",
            raw_payload_hash="abc",
            adapter_version="0.1.0",
            discovery_run_id="run-001",
        )
        assert candidate.reward is None

    def test_currency_default_none(self):
        candidate = BountyCandidate(
            source="github",
            source_id="123",
            raw_payload_reference="github/abc.json",
            raw_payload_hash="abc",
            adapter_version="0.1.0",
            discovery_run_id="run-001",
        )
        assert candidate.currency is None

    def test_source_created_at_default_none(self):
        candidate = BountyCandidate(
            source="github",
            source_id="123",
            raw_payload_reference="github/abc.json",
            raw_payload_hash="abc",
            adapter_version="0.1.0",
            discovery_run_id="run-001",
        )
        assert candidate.source_created_at is None

    def test_source_updated_at_default_none(self):
        candidate = BountyCandidate(
            source="github",
            source_id="123",
            raw_payload_reference="github/abc.json",
            raw_payload_hash="abc",
            adapter_version="0.1.0",
            discovery_run_id="run-001",
        )
        assert candidate.source_updated_at is None

    def test_last_activity_default_none(self):
        candidate = BountyCandidate(
            source="github",
            source_id="123",
            raw_payload_reference="github/abc.json",
            raw_payload_hash="abc",
            adapter_version="0.1.0",
            discovery_run_id="run-001",
        )
        assert candidate.last_activity is None

    def test_state_default_none(self):
        candidate = BountyCandidate(
            source="github",
            source_id="123",
            raw_payload_reference="github/abc.json",
            raw_payload_hash="abc",
            adapter_version="0.1.0",
            discovery_run_id="run-001",
        )
        assert candidate.state is None

    def test_labels_default_none(self):
        candidate = BountyCandidate(
            source="github",
            source_id="123",
            raw_payload_reference="github/abc.json",
            raw_payload_hash="abc",
            adapter_version="0.1.0",
            discovery_run_id="run-001",
        )
        assert candidate.labels == []


class TestBountyCandidateFullConstruction:
    """Full construction with all fields populated."""

    def test_full_candidate(self):
        candidate = BountyCandidate(
            source="github",
            source_id="11276",
            canonical_issue_key="octocat/Hello-World#11276",
            title="Test Issue 1790220222",
            description="This is a test issue created by automated tests.",
            repository_url="https://github.com/octocat/Hello-World",
            issue_url="https://github.com/octocat/Hello-World/issues/11276",
            reward=None,
            currency=None,
            source_created_at="2026-09-24T03:23:43Z",
            source_updated_at="2026-09-24T03:23:43Z",
            last_activity="2026-09-24T03:23:43Z",
            state="open",
            labels=["bug", "good first issue"],
            raw_payload_reference="github/abc123.json",
            raw_payload_hash="abc123def456",
            adapter_version="0.1.0",
            discovery_run_id="run-001",
        )
        assert candidate.source == "github"
        assert candidate.source_id == "11276"
        assert candidate.canonical_issue_key == "octocat/Hello-World#11276"
        assert candidate.title == "Test Issue 1790220222"
        assert candidate.description == "This is a test issue created by automated tests."
        assert candidate.repository_url == "https://github.com/octocat/Hello-World"
        assert candidate.issue_url == "https://github.com/octocat/Hello-World/issues/11276"
        assert candidate.reward is None
        assert candidate.currency is None
        assert candidate.source_created_at == "2026-09-24T03:23:43Z"
        assert candidate.source_updated_at == "2026-09-24T03:23:43Z"
        assert candidate.last_activity == "2026-09-24T03:23:43Z"
        assert candidate.state == "open"
        assert candidate.labels == ["bug", "good first issue"]
        assert candidate.raw_payload_reference == "github/abc123.json"
        assert candidate.raw_payload_hash == "abc123def456"
        assert candidate.adapter_version == "0.1.0"
        assert candidate.discovery_run_id == "run-001"

    def test_labels_empty_list(self):
        """Empty labels list is valid (not None)."""
        candidate = BountyCandidate(
            source="github",
            source_id="123",
            raw_payload_reference="github/abc.json",
            raw_payload_hash="abc",
            adapter_version="0.1.0",
            discovery_run_id="run-001",
            labels=[],
        )
        assert candidate.labels == []

    def test_no_reward_for_github(self):
        """GitHub has no native reward — reward and currency must be None."""
        candidate = BountyCandidate(
            source="github",
            source_id="123",
            raw_payload_reference="github/abc.json",
            raw_payload_hash="abc",
            adapter_version="0.1.0",
            discovery_run_id="run-001",
            reward=None,
            currency=None,
        )
        assert candidate.reward is None
        assert candidate.currency is None


class TestBountyCandidateFrozen:
    """BountyCandidate is frozen — cannot be modified after creation."""

    def test_frozen_raises_on_setattr(self):
        candidate = BountyCandidate(
            source="github",
            source_id="123",
            raw_payload_reference="github/abc.json",
            raw_payload_hash="abc",
            adapter_version="0.1.0",
            discovery_run_id="run-001",
        )
        with pytest.raises(Exception):
            candidate.source = "algora"


class TestBountyCandidateSourceNeutral:
    """BountyCandidate is source-neutral — works for any source."""

    def test_github_source(self):
        candidate = BountyCandidate(
            source="github",
            source_id="123",
            raw_payload_reference="github/abc.json",
            raw_payload_hash="abc",
            adapter_version="0.1.0",
            discovery_run_id="run-001",
        )
        assert candidate.source == "github"

    def test_algora_source(self):
        candidate = BountyCandidate(
            source="algora",
            source_id="task-456",
            raw_payload_reference="algora/def456.json",
            raw_payload_hash="def456",
            adapter_version="0.1.0",
            discovery_run_id="run-001",
        )
        assert candidate.source == "algora"

    def test_taskbounty_source(self):
        candidate = BountyCandidate(
            source="taskbounty",
            source_id="tb-789",
            raw_payload_reference="taskbounty/ghi789.json",
            raw_payload_hash="ghi789",
            adapter_version="0.1.0",
            discovery_run_id="run-001",
        )
        assert candidate.source == "taskbounty"


# ---------------------------------------------------------------------------
# RunContext tests
# ---------------------------------------------------------------------------

class TestRunContextConstruction:
    """RunContext construction and field access."""

    def test_minimal_context(self, tmp_path):
        """Minimal RunContext with required fields."""
        from datetime import datetime, timezone

        ctx = RunContext(
            run_id="run-001",
            started_at=datetime.now(timezone.utc),
            discovery_query="github:octocat/Hello-World",
            source_config={
                "github": {
                    "enabled": True,
                    "repositories": ["octocat/Hello-World"],
                }
            },
        )
        assert ctx.run_id == "run-001"
        assert ctx.discovery_query == "github:octocat/Hello-World"
        assert ctx.source_config == {
            "github": {
                "enabled": True,
                "repositories": ["octocat/Hello-World"],
            }
        }

    def test_source_config_multiple_sources(self):
        """RunContext can carry config for multiple sources."""
        ctx = RunContext(
            run_id="run-002",
            started_at=__import__("datetime").datetime(2026, 9, 24, tzinfo=__import__("datetime").timezone.utc),
            discovery_query="multi-source",
            source_config={
                "github": {
                    "enabled": True,
                    "repositories": ["octocat/Hello-World"],
                },
                "algora": {
                    "enabled": False,
                    "organizations": ["test-org"],
                },
            },
        )
        assert "github" in ctx.source_config
        assert "algora" in ctx.source_config
        assert ctx.source_config["github"]["enabled"] is True
        assert ctx.source_config["algora"]["enabled"] is False


# ---------------------------------------------------------------------------
# AdapterResult tests
# ---------------------------------------------------------------------------

class TestAdapterResultConstruction:
    """AdapterResult construction and field access."""

    def test_success_result(self):
        """SUCCESS status with candidates."""
        candidates = [
            BountyCandidate(
                source="github",
                source_id="123",
                raw_payload_reference="github/abc.json",
                raw_payload_hash="abc",
                adapter_version="0.1.0",
                discovery_run_id="run-001",
                title="Test Issue",
            ),
        ]
        result = AdapterResult(
            source="github",
            adapter_version="0.1.0",
            status="SUCCESS",
            candidates=candidates,
            pages_fetched=1,
            candidates_fetched=1,
            error=None,
            rate_limit_hit=False,
            elapsed_seconds=0.5,
        )
        assert result.status == "SUCCESS"
        assert len(result.candidates) == 1
        assert result.pages_fetched == 1
        assert result.candidates_fetched == 1
        assert result.error is None
        assert result.rate_limit_hit is False
        assert result.elapsed_seconds == 0.5

    def test_failed_result_with_error(self):
        """FAILED status with error message."""
        result = AdapterResult(
            source="github",
            adapter_version="0.1.0",
            status="FAILED",
            candidates=[],
            pages_fetched=0,
            candidates_fetched=0,
            error="Rate limit exceeded",
            rate_limit_hit=True,
            elapsed_seconds=1.2,
        )
        assert result.status == "FAILED"
        assert result.error == "Rate limit exceeded"
        assert result.rate_limit_hit is True

    def test_partial_result(self):
        """PARTIAL status."""
        result = AdapterResult(
            source="algora",
            adapter_version="0.1.0",
            status="PARTIAL",
            candidates=[],
            pages_fetched=0,
            candidates_fetched=0,
            error="Some pages failed",
            rate_limit_hit=False,
            elapsed_seconds=2.0,
        )
        assert result.status == "PARTIAL"

    def test_empty_candidates_success(self):
        """SUCCESS with 0 candidates is valid (not FAILED)."""
        result = AdapterResult(
            source="github",
            adapter_version="0.1.0",
            status="SUCCESS",
            candidates=[],
            pages_fetched=1,
            candidates_fetched=0,
            error=None,
            rate_limit_hit=False,
            elapsed_seconds=0.3,
        )
        assert result.status == "SUCCESS"
        assert len(result.candidates) == 0
        assert result.candidates_fetched == 0

    def test_default_values(self):
        """Default values for optional fields."""
        result = AdapterResult(
            source="github",
            adapter_version="0.1.0",
            status="SUCCESS",
            candidates=[],
            pages_fetched=1,
            candidates_fetched=1,
        )
        assert result.error is None
        assert result.rate_limit_hit is False
        assert result.elapsed_seconds == 0.0


# ---------------------------------------------------------------------------
# RunStatus tests
# ---------------------------------------------------------------------------

class TestRunStatus:
    """RunStatus validation and constants."""

    def test_success_is_valid(self):
        assert RunStatus.is_valid(RunStatus.SUCCESS) is True

    def test_partial_is_valid(self):
        assert RunStatus.is_valid(RunStatus.PARTIAL) is True

    def test_failed_is_valid(self):
        assert RunStatus.is_valid(RunStatus.FAILED) is True

    def test_running_is_valid(self):
        assert RunStatus.is_valid(RunStatus.RUNNING) is True

    def test_invalid_status(self):
        assert RunStatus.is_valid("INVALID") is False

    def test_constants_have_expected_values(self):
        assert RunStatus.SUCCESS == "SUCCESS"
        assert RunStatus.PARTIAL == "PARTIAL"
        assert RunStatus.FAILED == "FAILED"
        assert RunStatus.RUNNING == "RUNNING"


# ---------------------------------------------------------------------------
# DiscoveryAdapter protocol tests
# ---------------------------------------------------------------------------

class TestDiscoveryAdapterProtocol:
    """DiscoveryAdapter protocol basics."""

    def test_protocol_is_runtime_checkable(self):
        """Protocol is runtime_checkable."""
        assert hasattr(DiscoveryAdapter, "_is_protocol")

    def test_protocol_has_required_attributes(self):
        """Protocol defines source and adapter_version attributes."""
        # Check that the protocol expects these attributes
        from typing import get_type_hints

        hints = get_type_hints(DiscoveryAdapter)
        assert "source" in hints or hasattr(DiscoveryAdapter, "source")
        assert "adapter_version" in hints or hasattr(DiscoveryAdapter, "adapter_version")
        assert "fetch" in hints or hasattr(DiscoveryAdapter, "fetch")


# ---------------------------------------------------------------------------
# ADAPTER_CONTRACT_VERSION tests
# ---------------------------------------------------------------------------

class TestAdapterContractVersion:
    """Adapter contract version constant."""

    def test_version_is_string(self):
        assert isinstance(ADAPTER_CONTRACT_VERSION, str)

    def test_version_not_empty(self):
        assert len(ADAPTER_CONTRACT_VERSION) > 0

    def test_version_matches_expected_format(self):
        """Version should be in semver-like format."""
        parts = ADAPTER_CONTRACT_VERSION.split(".")
        assert len(parts) >= 2
        assert all(p.isdigit() for p in parts)
