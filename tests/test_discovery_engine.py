"""
Tests for hbh.discovery.engine — Phase 1b-GH-2A.

Discovery Engine Core / Orchestrator tests.

Scope: source-agnostic engine behavior only.
No GitHub adapter, no HTTP, no CLI, no policy/triage.
"""

from __future__ import annotations

import pytest

from hbh.core.config import Config
from hbh.core.database import Database, ensure_schema
from hbh.core.state_machine import BountyStatus
from hbh.discovery.engine import (
    DiscoveryEngine,
    DiscoveryRunResult,
    IngestionOutcome,
    MAX_TOTAL_CANDIDATES,
    MAX_RUN_DURATION_SECONDS,
    ValidationResult,
    create_discovery_engine,
)
from hbh.discovery.models import (
    AdapterStatus,
    AdapterResult,
    BountyCandidate,
    DiscoveryAdapter,
    RunContext,
    RunStatus,
    make_adapter_result,
    make_run_context,
)


# ---------------------------------------------------------------------------
# Mock adapters
# ---------------------------------------------------------------------------

class MockSuccessAdapter:
    def __init__(self, source: str = "mock", candidates: list[BountyCandidate] | None = None):
        self.source = source
        self.adapter_version = "1.0.0"
        self._candidates = candidates or []

    def fetch(self, run_context: RunContext) -> AdapterResult:
        return AdapterResult(
            source=self.source, adapter_version=self.adapter_version,
            status=AdapterStatus.SUCCESS, candidates=list(self._candidates),
            pages_fetched=1, candidates_fetched=len(self._candidates),
            error=None, rate_limit_hit=False, elapsed_seconds=0.1,
        )


class MockPartialAdapter:
    def __init__(self, source: str = "mock_partial", candidates: list[BountyCandidate] | None = None):
        self.source = source
        self.adapter_version = "1.0.0"
        self._candidates = candidates or []

    def fetch(self, run_context: RunContext) -> AdapterResult:
        return AdapterResult(
            source=self.source, adapter_version=self.adapter_version,
            status=AdapterStatus.PARTIAL, candidates=list(self._candidates),
            pages_fetched=1, candidates_fetched=len(self._candidates) + 5,
            error="Some candidates lost", rate_limit_hit=False, elapsed_seconds=0.1,
        )


class MockFailedAdapter:
    def __init__(self, source: str = "mock_failed"):
        self.source = source
        self.adapter_version = "1.0.0"

    def fetch(self, run_context: RunContext) -> AdapterResult:
        return AdapterResult(
            source=self.source, adapter_version=self.adapter_version,
            status=AdapterStatus.FAILED, candidates=[],
            pages_fetched=0, candidates_fetched=0,
            error="Service unavailable", rate_limit_hit=False, elapsed_seconds=0.1,
        )


class MockExceptionAdapter:
    def __init__(self, source: str = "mock_exception"):
        self.source = source
        self.adapter_version = "1.0.0"

    def fetch(self, run_context: RunContext) -> AdapterResult:
        raise RuntimeError("Simulated adapter crash")


class MockEmptySuccessAdapter:
    def __init__(self, source: str = "mock_empty"):
        self.source = source
        self.adapter_version = "1.0.0"

    def fetch(self, run_context: RunContext) -> AdapterResult:
        return AdapterResult(
            source=self.source, adapter_version=self.adapter_version,
            status=AdapterStatus.SUCCESS, candidates=[],
            pages_fetched=1, candidates_fetched=0,
            error=None, rate_limit_hit=False, elapsed_seconds=0.1,
        )


# Helper: build a BountyCandidate with all required fields
def _mk_candidate(source: str = "github", source_id: str = "123",
                  title: str = "Test Issue",
                  issue_url: str = "https://github.com/owner/repo/issues/123",
                  repository_url: str = "https://github.com/owner/repo",
                  raw_ref: str = "",
                  raw_hash: str = "",
                  adapter_version: str = "1.0.0",
                  discovery_run_id: str = "run-test") -> BountyCandidate:
    """Create a fully-valid BountyCandidate."""
    return BountyCandidate(
        source=source,
        source_id=source_id,
        discovery_run_id=discovery_run_id,
        canonical_issue_key=f"owner/repo#{source_id}",
        title=title,
        description="Test description",
        repository_url=repository_url,
        issue_url=issue_url,
        reward=None,
        currency=None,
        source_created_at="2026-01-01T00:00:00+00:00",
        source_updated_at="2026-01-01T00:00:00+00:00",
        last_activity="2026-01-01T00:00:00+00:00",
        state="open",
        labels=["bug"],
        raw_payload_reference=raw_ref or f"{source}/{source_id}.json",
        raw_payload_hash=raw_hash or f"hash_{source_id}",
        adapter_version=adapter_version,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_db(tmp_path):
    db_path = str(tmp_path / "test_engine.db")
    config = Config(hbhome=str(tmp_path))
    db = Database.create(config)
    ensure_schema(db)
    yield db
    db.close()


@pytest.fixture
def engine(temp_db):
    parent = str(temp_db.path.rsplit("test_engine.db", 1)[0])
    config = Config(hbhome=parent)
    return create_discovery_engine(config=config, db=temp_db)


# ===================================================================
# RUN LIFECYCLE
# ===================================================================

class TestRunLifecycle:
    def test_run_starts_running(self, engine):
        result = engine.run(adapters=[MockEmptySuccessAdapter()])
        assert result.status in (RunStatus.SUCCESS, RunStatus.FAILED, RunStatus.PARTIAL)
        row = engine.db.connection.execute(
            "SELECT status FROM discovery_runs WHERE run_id = ?", (result.run_id,)
        ).fetchone()
        assert row is not None

    def test_single_success_adapter(self, engine):
        result = engine.run(adapters=[MockSuccessAdapter()])
        assert result.status == RunStatus.SUCCESS
        assert result.adapters_total == 1
        assert result.adapters_succeeded == 1
        assert result.adapters_failed == 0

    def test_all_fail_to_failed(self, engine):
        result = engine.run(adapters=[MockFailedAdapter(), MockFailedAdapter()])
        assert result.status == RunStatus.FAILED
        assert result.adapters_succeeded == 0
        assert result.adapters_failed == 2

    def test_mixed_to_partial(self, engine):
        result = engine.run(adapters=[MockSuccessAdapter(), MockFailedAdapter()])
        assert result.status == RunStatus.PARTIAL
        assert result.adapters_succeeded == 1
        assert result.adapters_failed == 1

    def test_success_zero_candidates_still_success(self, engine):
        result = engine.run(adapters=[MockEmptySuccessAdapter()])
        assert result.status == RunStatus.SUCCESS
        assert result.candidates_inserted == 0

    def test_run_id_unique(self, engine):
        r1 = engine.run(adapters=[MockEmptySuccessAdapter()])
        r2 = engine.run(adapters=[MockEmptySuccessAdapter()])
        assert r1.run_id != r2.run_id
        assert r1.run_id.startswith("discovery-")


# ===================================================================
# ADAPTER ISOLATION
# ===================================================================

class TestAdapterIsolation:
    def test_successful_adapter_persists(self, engine):
        c = _mk_candidate(source="mock", source_id="c1")
        result = engine.run(adapters=[MockSuccessAdapter(candidates=[c])])
        assert result.status == RunStatus.SUCCESS
        assert result.candidates_inserted == 1

    def test_failed_adapter_does_not_stop_others(self, engine):
        good = _mk_candidate(source="good", source_id="gc1")
        result = engine.run(adapters=[
            MockFailedAdapter(source="bad"),
            MockSuccessAdapter(source="good", candidates=[good]),
        ])
        assert result.status == RunStatus.PARTIAL
        assert result.adapters_succeeded == 1
        assert result.adapters_failed == 1
        assert result.candidates_inserted == 1

    def test_exception_adapter_caught(self, engine):
        good = _mk_candidate(source="good", source_id="gc1")
        result = engine.run(adapters=[
            MockSuccessAdapter(source="good", candidates=[good]),
            MockExceptionAdapter(source="bad"),
        ])
        assert result.status == RunStatus.PARTIAL
        assert result.adapters_succeeded == 1
        assert result.adapters_failed == 1


# ===================================================================
# CANDIDATE VALIDATION
# ===================================================================

class TestCandidateValidation:
    def test_valid_candidate_passes(self, engine):
        c = _mk_candidate(source="github", source_id="123")
        result = engine.run(adapters=[MockSuccessAdapter(candidates=[c])])
        assert result.status == RunStatus.SUCCESS
        assert result.candidates_inserted == 1

    def test_missing_source_rejected(self, engine):
        with pytest.raises(ValueError, match="source must not be empty"):
            BountyCandidate(
                source="", source_id="123", discovery_run_id="run-test",
                canonical_issue_key="owner/repo#123", title="Test",
                description="Test", repository_url="https://example.com/repo",
                issue_url="https://example.com/repo/issues/123", reward=None, currency=None,
                source_created_at="2026-01-01T00:00:00+00:00", source_updated_at="2026-01-01T00:00:00+00:00",
                last_activity="2026-01-01T00:00:00+00:00", state="open", labels=["bug"],
                raw_payload_reference="github/123.json", raw_payload_hash="hash_123",
                adapter_version="1.0.0",
            )
        # Engine can never see a candidate with empty source; model rejects at construction.

    def test_missing_source_id_rejected(self, engine):
        with pytest.raises(ValueError, match="source_id must not be empty"):
            BountyCandidate(
                source="github", source_id="", discovery_run_id="run-test",
                canonical_issue_key="owner/repo#123", title="Test",
                description="Test", repository_url="https://example.com/repo",
                issue_url="https://example.com/repo/issues/123", reward=None, currency=None,
                source_created_at="2026-01-01T00:00:00+00:00", source_updated_at="2026-01-01T00:00:00+00:00",
                last_activity="2026-01-01T00:00:00+00:00", state="open", labels=["bug"],
                raw_payload_reference="github/123.json", raw_payload_hash="hash_123",
                adapter_version="1.0.0",
            )
        # Engine can never see a candidate with empty source_id; model rejects at construction.

    def test_missing_title_rejected(self, engine):
        c = BountyCandidate(
            source="github", source_id="123", discovery_run_id="run-test",
            canonical_issue_key="owner/repo#123", title="",
            description="Test", repository_url="https://example.com/repo",
            issue_url="https://example.com/repo/issues/123", reward=None, currency=None,
            source_created_at="2026-01-01T00:00:00+00:00", source_updated_at="2026-01-01T00:00:00+00:00",
            last_activity="2026-01-01T00:00:00+00:00", state="open", labels=["bug"],
            raw_payload_reference="github/123.json", raw_payload_hash="hash_123",
            adapter_version="1.0.0",
        )
        result = engine.run(adapters=[MockSuccessAdapter(candidates=[c])])
        assert result.candidates_inserted == 0

    def test_missing_discovery_run_id_rejected(self, engine):
        c = BountyCandidate(
            source="github", source_id="123", discovery_run_id="",
            canonical_issue_key="owner/repo#123", title="Test",
            description="Test", repository_url="https://example.com/repo",
            issue_url="https://example.com/repo/issues/123", reward=None, currency=None,
            source_created_at="2026-01-01T00:00:00+00:00", source_updated_at="2026-01-01T00:00:00+00:00",
            last_activity="2026-01-01T00:00:00+00:00", state="open", labels=["bug"],
            raw_payload_reference="github/123.json", raw_payload_hash="hash_123",
            adapter_version="1.0.0",
        )
        result = engine.run(adapters=[MockSuccessAdapter(candidates=[c])])
        assert result.candidates_inserted == 0

    def test_missing_raw_payload_reference_rejected(self, engine):
        # GH-2B: raw_payload_reference is now an OUTPUT field generated by
        # raw_storage, not an input validation requirement.
        # Without raw_storage configured, the engine still accepts the
        # candidate and writes raw_ref=None to DB.
        c = BountyCandidate(
            source="github", source_id="123", discovery_run_id="run-test",
            canonical_issue_key="owner/repo#123", title="Test",
            description="Test", repository_url="https://example.com/repo",
            issue_url="https://example.com/repo/issues/123", reward=None, currency=None,
            source_created_at="2026-01-01T00:00:00+00:00", source_updated_at="2026-01-01T00:00:00+00:00",
            last_activity="2026-01-01T00:00:00+00:00", state="open", labels=["bug"],
            raw_payload_reference="", raw_payload_hash="hash_123",
            adapter_version="1.0.0",
        )
        result = engine.run(adapters=[MockSuccessAdapter(candidates=[c])])
        assert result.candidates_inserted == 1
        # Verify DB record has raw_payload_reference=None (no raw storage)
        row = engine.db.connection.execute(
            "SELECT raw_payload_reference FROM bounties WHERE source = ? AND source_id = ?",
            ("github", "123"),
        ).fetchone()
        assert row is not None
        assert row["raw_payload_reference"] is None

    def test_missing_raw_payload_hash_rejected(self, engine):
        # GH-2B: raw_payload_hash is now an OUTPUT field generated by
        # raw_storage, not an input validation requirement.
        c = BountyCandidate(
            source="github", source_id="123", discovery_run_id="run-test",
            canonical_issue_key="owner/repo#123", title="Test",
            description="Test", repository_url="https://example.com/repo",
            issue_url="https://example.com/repo/issues/123", reward=None, currency=None,
            source_created_at="2026-01-01T00:00:00+00:00", source_updated_at="2026-01-01T00:00:00+00:00",
            last_activity="2026-01-01T00:00:00+00:00", state="open", labels=["bug"],
            raw_payload_reference="github/123.json", raw_payload_hash="",
            adapter_version="1.0.0",
        )
        result = engine.run(adapters=[MockSuccessAdapter(candidates=[c])])
        assert result.candidates_inserted == 1
        # Verify DB record has raw_payload_hash=None (no raw storage)
        row = engine.db.connection.execute(
            "SELECT raw_payload_hash FROM bounties WHERE source = ? AND source_id = ?",
            ("github", "123"),
        ).fetchone()
        assert row is not None
        assert row["raw_payload_hash"] is None

    def test_missing_adapter_version_rejected(self, engine):
        c = BountyCandidate(
            source="github", source_id="123", discovery_run_id="run-test",
            canonical_issue_key="owner/repo#123", title="Test",
            description="Test", repository_url="https://example.com/repo",
            issue_url="https://example.com/repo/issues/123", reward=None, currency=None,
            source_created_at="2026-01-01T00:00:00+00:00", source_updated_at="2026-01-01T00:00:00+00:00",
            last_activity="2026-01-01T00:00:00+00:00", state="open", labels=["bug"],
            raw_payload_reference="github/123.json", raw_payload_hash="hash_123",
            adapter_version="",
        )
        result = engine.run(adapters=[MockSuccessAdapter(candidates=[c])])
        assert result.candidates_inserted == 0

    def test_invalid_url_rejected(self, engine):
        c = _mk_candidate(source="github", source_id="123", issue_url="not-a-url")
        result = engine.run(adapters=[MockSuccessAdapter(candidates=[c])])
        assert result.candidates_inserted == 0

    def test_missing_url_rejected(self, engine):
        c = _mk_candidate(source="github", source_id="123",
                          **{"issue_url": "", "repository_url": ""})
        result = engine.run(adapters=[MockSuccessAdapter(candidates=[c])])
        assert result.candidates_inserted == 0

    def test_valid_url_passes(self, engine):
        c1 = _mk_candidate(source="github", source_id="111", issue_url="https://example.com/111")
        c2 = _mk_candidate(source="github", source_id="222", issue_url="http://example.com/222")
        result = engine.run(adapters=[MockSuccessAdapter(candidates=[c1, c2])])
        assert result.candidates_inserted == 2

    def test_ftp_url_rejected(self, engine):
        c = _mk_candidate(source="github", source_id="123", issue_url="ftp://example.com/file")
        result = engine.run(adapters=[MockSuccessAdapter(candidates=[c])])
        assert result.candidates_inserted == 0

    def test_valid_and_invalid_mixed(self, engine):
        valid = _mk_candidate(source="github", source_id="valid1", title="Valid")
        invalid = _mk_candidate(source="github", source_id="invalid1",
                                **{"title": ""})
        result = engine.run(adapters=[MockSuccessAdapter(candidates=[valid, invalid])])
        assert result.candidates_inserted == 1


# ===================================================================
# DUPLICATE HANDLING
# ===================================================================

class TestDuplicateHandling:
    def test_duplicate_not_inserted(self, engine):
        c = _mk_candidate(source="github", source_id="123")
        r1 = engine.run(adapters=[MockSuccessAdapter(candidates=[c])])
        assert r1.candidates_inserted == 1
        r2 = engine.run(adapters=[MockSuccessAdapter(candidates=[c])])
        assert r2.candidates_inserted == 0
        assert r2.candidates_duplicate == 1

    def test_different_sources_same_id_allowed(self, engine):
        c1 = _mk_candidate(source="github", source_id="123", title="GitHub Issue")
        c2 = _mk_candidate(source="algora", source_id="123", title="Algora Task",
                           issue_url="https://algora.example.com/task/123",
                           raw_ref="algora/123.json", raw_hash="algora_hash_123")
        result = engine.run(adapters=[MockSuccessAdapter(candidates=[c1, c2])])
        assert result.candidates_inserted == 2

    def test_same_source_different_id_allowed(self, engine):
        c1 = _mk_candidate(source="github", source_id="111")
        c2 = _mk_candidate(source="github", source_id="222")
        result = engine.run(adapters=[MockSuccessAdapter(candidates=[c1, c2])])
        assert result.candidates_inserted == 2


# ===================================================================
# TOTAL CANDIDATE LIMIT
# ===================================================================

class TestTotalCandidateLimit:
    def test_under_limit_all_inserted(self, engine):
        candidates = [_mk_candidate(source="github", source_id=str(i), title=f"Issue {i}")
                      for i in range(10)]
        result = engine.run(adapters=[MockSuccessAdapter(candidates=candidates)])
        assert result.candidates_inserted == 10

    def test_over_limit_truncated(self, tmp_path):
        config = Config(hbhome=str(tmp_path))
        db = Database.create(config)
        ensure_schema(db)
        eng = create_discovery_engine(config=config, db=db)

        candidates = [_mk_candidate(source="github", source_id=str(i), title=f"Issue {i}",
                                     issue_url=f"https://github.com/owner/repo/issues/{i}",
                                     raw_ref=f"github/{i}.json", raw_hash=f"hash{i}")
                      for i in range(250)]
        result = eng.run(adapters=[MockSuccessAdapter(candidates=candidates)])
        assert result.candidates_inserted == MAX_TOTAL_CANDIDATES
        assert result.limit_reached is True
        assert result.limit_reason == "max_total_candidates_reached"
        db.close()

    def test_exactly_at_limit_all_inserted(self, tmp_path):
        config = Config(hbhome=str(tmp_path))
        db = Database.create(config)
        ensure_schema(db)
        eng = create_discovery_engine(config=config, db=db)

        candidates = [_mk_candidate(source="github", source_id=str(i), title=f"Issue {i}",
                                     issue_url=f"https://github.com/owner/repo/issues/{i}",
                                     raw_ref=f"github/{i}.json", raw_hash=f"hash{i}")
                      for i in range(MAX_TOTAL_CANDIDATES)]
        result = eng.run(adapters=[MockSuccessAdapter(candidates=candidates)])
        assert result.candidates_inserted == MAX_TOTAL_CANDIDATES
        assert result.limit_reached is False
        db.close()

    def test_limit_blocks_further_processing(self, tmp_path):
        config = Config(hbhome=str(tmp_path))
        db = Database.create(config)
        ensure_schema(db)
        eng = create_discovery_engine(config=config, db=db)

        first_batch = [_mk_candidate(source="github", source_id=f"a{i}", title=f"Issue A{i}",
                                      issue_url=f"https://github.com/owner/repo/issues/{i}",
                                      raw_ref=f"github/a{i}.json", raw_hash=f"hash_a{i}")
                       for i in range(MAX_TOTAL_CANDIDATES + 1)]
        r1 = eng.run(adapters=[MockSuccessAdapter(candidates=first_batch)])
        assert r1.candidates_inserted == MAX_TOTAL_CANDIDATES
        assert r1.limit_reached is True
        db.close()


# ===================================================================
# SOURCE AGNOSTIC
# ===================================================================

class TestSourceAgnostic:
    def test_works_with_custom_source(self, engine):
        adapter = MockSuccessAdapter(source="custom_platform", candidates=[])
        result = engine.run(adapters=[adapter])
        assert result.status == RunStatus.SUCCESS

    def test_accepts_multiple_sources(self, engine):
        c1 = _mk_candidate(source="source_a", source_id="1", title="A",
                           issue_url="https://example.com/a",
                           raw_ref="a/ref", raw_hash="a_hash")
        c2 = _mk_candidate(source="source_b", source_id="1", title="B",
                           issue_url="https://example.com/b",
                           raw_ref="b/ref", raw_hash="b_hash")
        result = engine.run(adapters=[
            MockSuccessAdapter(source="source_a", candidates=[c1]),
            MockSuccessAdapter(source="source_b", candidates=[c2]),
        ])
        assert result.status == RunStatus.SUCCESS
        assert result.candidates_inserted == 2

    def test_no_github_specific_branching(self, engine):
        adapter = MockSuccessAdapter(source="custom_platform", candidates=[])
        result = engine.run(adapters=[adapter])
        assert result.status == RunStatus.SUCCESS


# ===================================================================
# DURATION LIMIT
# ===================================================================

class TestDurationLimit:
    def test_normal_run_under_limit(self, engine):
        result = engine.run(adapters=[MockSuccessAdapter()])
        assert result.duration_seconds < MAX_RUN_DURATION_SECONDS
        assert result.limit_reached is False

    def test_hard_limit_value_is_300(self):
        assert MAX_RUN_DURATION_SECONDS == 300


# ===================================================================
# HARD LIMITS
# ===================================================================

class TestHardLimits:
    def test_max_total_candidates_is_200(self):
        assert MAX_TOTAL_CANDIDATES == 200

    def test_max_run_duration_is_300(self):
        assert MAX_RUN_DURATION_SECONDS == 300


# ===================================================================
# VALIDATIONRESULT
# ===================================================================

class TestValidationResult:
    def test_ok(self):
        r = ValidationResult.ok()
        assert r.valid is True
        assert r.reason is None

    def test_invalid(self):
        r = ValidationResult.invalid("missing_title", "title")
        assert r.valid is False
        assert r.reason == "missing_title"
        assert r.field == "title"

    def test_frozen(self):
        r = ValidationResult.ok()
        with pytest.raises(Exception):
            r.valid = False


# ===================================================================
# INGESTION OUTCOME
# ===================================================================

class TestIngestionOutcome:
    def test_discovered(self):
        assert IngestionOutcome.DISCOVERED == "DISCOVERED"

    def test_rejected(self):
        assert IngestionOutcome.REJECTED == "DISCOVERY_REJECTED"

    def test_duplicate(self):
        assert IngestionOutcome.DUPLICATE == "DISCOVERY_DUPLICATE"


# ===================================================================
# DISCOVERY RUN RESULT
# ===================================================================

class TestDiscoveryRunResult:
    def test_immutable(self):
        r = DiscoveryRunResult(
            run_id="test-1", status=RunStatus.SUCCESS,
            started_at="2026-01-01T00:00:00", finished_at="2026-01-01T00:01:00",
            adapters_total=1, adapters_succeeded=1, adapters_failed=0,
            candidates_found=0, candidates_inserted=0, candidates_duplicate=0,
            duration_seconds=60.0, limit_reached=False, limit_reason=None,
        )
        with pytest.raises(Exception):
            r.status = RunStatus.FAILED

    def test_to_dict(self):
        r = DiscoveryRunResult(
            run_id="test-1", status=RunStatus.SUCCESS,
            started_at="2026-01-01T00:00:00", finished_at="2026-01-01T00:01:00",
            adapters_total=1, adapters_succeeded=1, adapters_failed=0,
            candidates_found=5, candidates_inserted=5, candidates_duplicate=0,
            duration_seconds=60.0, limit_reached=False, limit_reason=None,
        )
        d = r.to_dict()
        assert d["run_id"] == "test-1"
        assert d["status"] == RunStatus.SUCCESS
        assert d["candidates_inserted"] == 5


# ===================================================================
# PERSISTENCE BOUNDARY
# ===================================================================

class TestPersistenceBoundary:
    def test_bounties_persisted(self, engine):
        c = _mk_candidate(source="github", source_id="persist1")
        result = engine.run(adapters=[MockSuccessAdapter(candidates=[c])])
        assert result.candidates_inserted == 1

        row = engine.db.connection.execute(
            "SELECT * FROM bounties WHERE source = ? AND source_id = ?",
            ("github", "persist1"),
        ).fetchone()
        assert row is not None
        assert row["title"] == "Test Issue"
        assert row["status"] == BountyStatus.DISCOVERED.value

    def test_discovery_run_persisted(self, engine):
        result = engine.run(adapters=[MockSuccessAdapter()])
        row = engine.db.connection.execute(
            "SELECT * FROM discovery_runs WHERE run_id = ?", (result.run_id,)
        ).fetchone()
        assert row is not None
        assert row["status"] == RunStatus.SUCCESS

    def test_events_persisted(self, engine):
        result = engine.run(adapters=[MockSuccessAdapter()])
        events = engine.db.connection.execute(
            "SELECT COUNT(*) AS c FROM events WHERE entity_id = ?", (result.run_id,)
        ).fetchone()
        assert events["c"] >= 1


# ===================================================================
# SECRET HANDLING
# ===================================================================

class TestSecretHandling:
    def test_no_secrets_in_db(self, tmp_path):
        config = Config(hbhome=str(tmp_path))
        db = Database.create(config)
        ensure_schema(db)
        c = _mk_candidate(source="github", source_id="test1")
        eng = create_discovery_engine(config=config, db=db)
        eng.run(adapters=[MockSuccessAdapter(candidates=[c])])

        rows = db.connection.execute("SELECT * FROM bounties").fetchall()
        for row in rows:
            for val in row:
                if isinstance(val, str):
                    assert "sk-" not in val, f"Possible secret in DB: {val[:50]}"
                    assert "ghp_" not in val, f"Possible GitHub token in DB: {val[:50]}"
        db.close()


# ===================================================================
# REGRESSION
# ===================================================================

class TestRegression:
    def test_basic_db_ops(self, temp_db):
        from hbh.core.database import insert_bounty, count_bounties
        insert_bounty(temp_db, id="b-1", platform="test", url="http://test", title="Test", status="unknown")
        assert count_bounties(temp_db) == 1

    def test_state_machine_still_works(self):
        from hbh.core.state_machine import is_valid_transition, BountyStatus
        assert is_valid_transition(BountyStatus.DISCOVERED, BountyStatus.PROFILED) is True
        assert is_valid_transition(BountyStatus.DISCOVERED, BountyStatus.ACCEPTED) is False
