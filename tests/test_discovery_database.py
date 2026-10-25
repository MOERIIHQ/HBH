"""
Tests for hbh.core.database — Discovery schema migration — Phase 1b-GH-1.

Focused tests for:
- Schema migration v1 → v2 (additive, idempotent, data-preserving)
- discovery_runs table creation and CRUD
- Discovery columns on bounties table
- Existing Phase 0 data preservation

No GitHub adapter tests — those belong in a later subphase.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

import pytest

from hbh.core.config import load_config
from hbh.core.database import (
    Database,
    ensure_schema,
    current_schema_version,
    is_initialized,
    validate_schema_version,
    SchemaMismatchError,
    DatabaseError,
    insert_bounty,
    insert_event,
    count_bounties,
    # Discovery CRUD helpers
    insert_discovery_run,
    update_discovery_run,
    get_discovery_run,
    list_discovery_runs,
    count_discovery_runs,
    insert_discovered_bounty,
    get_discovered_bounties_by_run,
    exists_source_source_id,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_dir(tmp_path):
    """Return a temporary directory as a Path object."""
    return tmp_path


@pytest.fixture
def config(temp_dir):
    """Create a Config pointing to a temp DB and policy."""
    return load_config(
        hbhome=str(temp_dir),
        db_path=str(temp_dir / "test.db"),
        policy_path=str(temp_dir / "config" / "default_policy.yaml"),
        discovery_config_path=str(temp_dir / "config" / "discovery_config.yaml"),
    )


@pytest.fixture
def db(config, temp_dir):
    """Create a Database with v2 schema applied."""
    cfg = load_config(
        hbhome=config.home,
        db_path=str(temp_dir / "test.db"),
        policy_path=config.policy_path,
        discovery_config_path=config.discovery_config_path,
    )
    database = Database.create(cfg)
    ensure_schema(database)
    yield database
    database.close()


@pytest.fixture
def v1_db(config, temp_dir):
    """Create a Database with ONLY v1 schema (no discovery extension)."""
    cfg = load_config(
        hbhome=config.home,
        db_path=str(temp_dir / "v1_test.db"),
        policy_path=config.policy_path,
        discovery_config_path=config.discovery_config_path,
    )
    db = Database.create(cfg)
    # Manually apply only v1 schema (the _CREATE_TABLES DDL)
    with db.connection:
        db.connection.executescript("""
            CREATE TABLE IF NOT EXISTS schema_versions (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS bounties (
                id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                reward TEXT,
                created_at TEXT,
                discovered_at TEXT,
                status TEXT NOT NULL DEFAULT 'unknown'
            );
            CREATE TABLE IF NOT EXISTS repositories (
                repo_id TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                name TEXT NOT NULL,
                size_kb INTEGER,
                language TEXT,
                default_branch TEXT,
                last_push TEXT,
                has_lfs INTEGER NOT NULL DEFAULT 0,
                profile_status TEXT NOT NULL DEFAULT 'pending'
            );
            CREATE TABLE IF NOT EXISTS triage (
                bounty_id TEXT PRIMARY KEY,
                complexity REAL,
                competition REAL,
                feasibility REAL,
                risk REAL,
                estimated_cost REAL,
                expected_value REAL,
                decision TEXT,
                FOREIGN KEY (bounty_id) REFERENCES bounties(id)
            );
            CREATE TABLE IF NOT EXISTS executions (
                execution_id TEXT PRIMARY KEY,
                bounty_id TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                failure_reason TEXT,
                api_cost REAL DEFAULT 0,
                network_bytes INTEGER DEFAULT 0,
                diff_lines INTEGER DEFAULT 0,
                FOREIGN KEY (bounty_id) REFERENCES bounties(id)
            );
            CREATE TABLE IF NOT EXISTS outcomes (
                bounty_id TEXT PRIMARY KEY,
                validation_status TEXT NOT NULL DEFAULT 'pending',
                pr_status TEXT NOT NULL DEFAULT 'none',
                human_intervention INTEGER NOT NULL DEFAULT 0,
                final_result TEXT,
                FOREIGN KEY (bounty_id) REFERENCES bounties(id)
            );
            CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id TEXT NOT NULL,
                from_state TEXT,
                to_state TEXT,
                actor TEXT NOT NULL,
                reason TEXT,
                timestamp TEXT NOT NULL,
                metadata TEXT
            );
            INSERT INTO schema_versions (version, applied_at) VALUES (1, '2026-01-01T00:00:00');
        """)
        db.connection.commit()
    yield db
    db.close()


# ---------------------------------------------------------------------------
# Schema version tests
# ---------------------------------------------------------------------------

class TestSchemaVersionV3:
    """Verify schema version is 3 after ensure_schema."""

    def test_schema_version_is_three_after_ensure(self, db):
        version = current_schema_version(db)
        assert version == 3

    def test_initialized_after_ensure(self, db):
        assert is_initialized(db) is True


class TestSchemaVersionValidation:
    """validate_schema_version must accept v3 and reject unsupported versions."""

    def test_v3_accepted(self, db):
        # Should not raise
        validate_schema_version(db)

    def test_v1_migrated_to_v3(self, v1_db, temp_dir):
        """A v1 database should be migrated to v3 on ensure_schema.

        Migration path: v1 -> v2 (discovery extension) -> v3 (repository
        profiling tables + indexes). Existing data must be preserved.
        """
        # Insert some data before migration
        from hbh.core.database import insert_bounty

        insert_bounty(
            v1_db,
            id="b-1",
            platform="github",
            url="https://example.com",
            title="Old Title",
            status="unknown",
        )
        insert_bounty(
            v1_db,
            id="b-2",
            platform="algora",
            url="https://algora.example.com",
            title="Another Old",
            status="unknown",
        )

        count_before = count_bounties(v1_db)
        assert count_before == 2

        # Before migration, v1_db has version 1
        assert current_schema_version(v1_db) == 1

        # Now apply ensure_schema (which should migrate v1 -> v3)
        from hbh.core.database import ensure_schema as es

        es(v1_db)

        # Data must still be there (v1 -> v2 additive migration)
        count_after = count_bounties(v1_db)
        assert count_after == 2

        # Schema version must now be 3
        assert current_schema_version(v1_db) == 3

    def test_unsupported_version_still_raises(self, temp_dir):
        """A database with version 4 should still raise SchemaMismatchError."""
        import sqlite3

        path = str(temp_dir / "bad_v4.db")
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE schema_versions (version INTEGER PRIMARY KEY, applied_at TEXT)"
        )
        conn.execute(
            "INSERT INTO schema_versions (version, applied_at) VALUES (4, '2026-01-01T00:00:00')"
        )
        conn.commit()
        conn.close()

        db = Database.connect(path)
        with pytest.raises(
            SchemaMismatchError, match="not supported"
        ):
            validate_schema_version(db)
        db.close()


# ---------------------------------------------------------------------------
# Discovery columns on bounties tests
# ---------------------------------------------------------------------------

class TestBountiesDiscoveryColumns:
    """Verify discovery columns exist on bounties table after migration."""

    def test_source_column_exists(self, db):
        row = db.connection.execute(
            "PRAGMA table_info(bounties)"
        ).fetchall()
        column_names = [r["name"] for r in row]
        assert "source" in column_names

    def test_source_id_column_exists(self, db):
        row = db.connection.execute(
            "PRAGMA table_info(bounties)"
        ).fetchall()
        column_names = [r["name"] for r in row]
        assert "source_id" in column_names

    def test_canonical_issue_key_column_exists(self, db):
        row = db.connection.execute(
            "PRAGMA table_info(bounties)"
        ).fetchall()
        column_names = [r["name"] for r in row]
        assert "canonical_issue_key" in column_names

    def test_repository_url_column_exists(self, db):
        row = db.connection.execute(
            "PRAGMA table_info(bounties)"
        ).fetchall()
        column_names = [r["name"] for r in row]
        assert "repository_url" in column_names

    def test_issue_url_column_exists(self, db):
        row = db.connection.execute(
            "PRAGMA table_info(bounties)"
        ).fetchall()
        column_names = [r["name"] for r in row]
        assert "issue_url" in column_names

    def test_currency_column_exists(self, db):
        row = db.connection.execute(
            "PRAGMA table_info(bounties)"
        ).fetchall()
        column_names = [r["name"] for r in row]
        assert "currency" in column_names

    def test_source_created_at_column_exists(self, db):
        row = db.connection.execute(
            "PRAGMA table_info(bounties)"
        ).fetchall()
        column_names = [r["name"] for r in row]
        assert "source_created_at" in column_names

    def test_source_updated_at_column_exists(self, db):
        row = db.connection.execute(
            "PRAGMA table_info(bounties)"
        ).fetchall()
        column_names = [r["name"] for r in row]
        assert "source_updated_at" in column_names

    def test_last_activity_column_exists(self, db):
        row = db.connection.execute(
            "PRAGMA table_info(bounties)"
        ).fetchall()
        column_names = [r["name"] for r in row]
        assert "last_activity" in column_names

    def test_state_column_exists(self, db):
        row = db.connection.execute(
            "PRAGMA table_info(bounties)"
        ).fetchall()
        column_names = [r["name"] for r in row]
        assert "state" in column_names

    def test_labels_column_exists(self, db):
        row = db.connection.execute(
            "PRAGMA table_info(bounties)"
        ).fetchall()
        column_names = [r["name"] for r in row]
        assert "labels" in column_names

    def test_raw_payload_reference_column_exists(self, db):
        row = db.connection.execute(
            "PRAGMA table_info(bounties)"
        ).fetchall()
        column_names = [r["name"] for r in row]
        assert "raw_payload_reference" in column_names

    def test_raw_payload_hash_column_exists(self, db):
        row = db.connection.execute(
            "PRAGMA table_info(bounties)"
        ).fetchall()
        column_names = [r["name"] for r in row]
        assert "raw_payload_hash" in column_names

    def test_adapter_version_column_exists(self, db):
        row = db.connection.execute(
            "PRAGMA table_info(bounties)"
        ).fetchall()
        column_names = [r["name"] for r in row]
        assert "adapter_version" in column_names

    def test_discovery_run_id_column_exists(self, db):
        row = db.connection.execute(
            "PRAGMA table_info(bounties)"
        ).fetchall()
        column_names = [r["name"] for r in row]
        assert "discovery_run_id" in column_names

    def test_all_required_discovery_columns_exist(self, db):
        """All discovery columns from the architecture review must exist."""
        expected_columns = {
            "source",
            "source_id",
            "canonical_issue_key",
            "repository_url",
            "issue_url",
            "currency",
            "source_created_at",
            "source_updated_at",
            "last_activity",
            "state",
            "labels",
            "raw_payload_reference",
            "raw_payload_hash",
            "adapter_version",
            "discovery_run_id",
        }
        row = db.connection.execute(
            "PRAGMA table_info(bounties)"
        ).fetchall()
        actual_columns = {r["name"] for r in row}
        missing = expected_columns - actual_columns
        assert not missing, f"Missing columns: {missing}"


# ---------------------------------------------------------------------------
# discovery_runs table tests
# ---------------------------------------------------------------------------

class TestDiscoveryRunsTable:
    """Verify discovery_runs table exists and has correct columns."""

    def test_discovery_runs_table_exists(self, db):
        row = db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='discovery_runs'"
        ).fetchone()
        assert row is not None

    def test_discovery_runs_required_columns(self, db):
        """All required discovery_runs columns must exist."""
        expected_columns = {
            "run_id",
            "started_at",
            "finished_at",
            "status",
            "trigger",
            "adapters_total",
            "adapters_succeeded",
            "adapters_failed",
            "candidates_found",
            "candidates_inserted",
            "candidates_duplicate",
            "error_summary",
        }
        row = db.connection.execute(
            "PRAGMA table_info(discovery_runs)"
        ).fetchall()
        actual_columns = {r["name"] for r in row}
        missing = expected_columns - actual_columns
        assert not missing, f"Missing columns: {missing}"

    def test_discovery_runs_primary_key(self, db):
        """discovery_runs must have run_id as PRIMARY KEY."""
        rows = db.connection.execute(
            "PRAGMA table_info(discovery_runs)"
        ).fetchall()
        pk_rows = [r for r in rows if r["pk"] > 0]
        assert len(pk_rows) == 1
        assert pk_rows[0]["name"] == "run_id"


# ---------------------------------------------------------------------------
# Migration idempotency tests
# ---------------------------------------------------------------------------

class TestMigrationIdempotency:
    """Migration must be safe to run multiple times."""

    def test_double_ensure_schema_no_error(self, db, temp_dir):
        """Calling ensure_schema twice must not raise."""
        # First call already done in fixture
        # Second call
        ensure_schema(db)
        assert current_schema_version(db) == 3

    def test_migration_preserves_existing_data(self, v1_db, temp_dir):
        """Migrating a v1 database with existing data must preserve it."""
        # Insert some v1 data before migration
        insert_bounty(
            v1_db,
            id="b-1",
            platform="github",
            url="https://example.com",
            title="Old Title",
            status="unknown",
        )
        insert_bounty(
            v1_db,
            id="b-2",
            platform="algora",
            url="https://algora.example.com",
            title="Another Old",
            status="unknown",
        )

        count_before = count_bounties(v1_db)
        assert count_before == 2

        # Now migrate to v2
        from hbh.core.database import ensure_schema as es

        es(v1_db)

        # Data must still be there
        count_after = count_bounties(v1_db)
        assert count_after == 2

        # Check specific row
        row = v1_db.connection.execute(
            "SELECT id, platform, title FROM bounties WHERE id = ?",
            ("b-1",),
        ).fetchone()
        assert row is not None
        assert row["id"] == "b-1"
        assert row["platform"] == "github"
        assert row["title"] == "Old Title"


# ---------------------------------------------------------------------------
# discovery_runs CRUD tests
# ---------------------------------------------------------------------------

class TestDiscoveryRunCRUD:
    """CRUD operations on discovery_runs."""

    def test_insert_discovery_run(self, db):
        """Insert a discovery run and verify it exists."""
        insert_discovery_run(
            db,
            run_id="run-001",
            started_at="2026-09-24T12:00:00Z",
            trigger="manual",
        )
        run = get_discovery_run(db, "run-001")
        assert run is not None
        assert run["run_id"] == "run-001"
        assert run["started_at"] == "2026-09-24T12:00:00Z"
        assert run["status"] == "RUNNING"
        assert run["trigger"] == "manual"
        assert run["adapters_total"] == 0
        assert run["adapters_succeeded"] == 0
        assert run["adapters_failed"] == 0
        assert run["candidates_found"] == 0
        assert run["candidates_inserted"] == 0
        assert run["candidates_duplicate"] == 0
        assert run["error_summary"] is None or row_is_none(run["error_summary"])

    def test_update_discovery_run(self, db):
        """Update a discovery run with completion data."""
        insert_discovery_run(
            db,
            run_id="run-002",
            started_at="2026-09-24T12:00:00Z",
            trigger="manual",
        )
        update_discovery_run(
            db,
            run_id="run-002",
            finished_at="2026-09-24T12:05:00Z",
            status="SUCCESS",
            adapters_total=1,
            adapters_succeeded=1,
            adapters_failed=0,
            candidates_found=5,
            candidates_inserted=5,
            candidates_duplicate=0,
            error_summary=None,
        )
        run = get_discovery_run(db, "run-002")
        assert run is not None
        assert run["status"] == "SUCCESS"
        assert run["finished_at"] == "2026-09-24T12:05:00Z"
        assert run["adapters_total"] == 1
        assert run["adapters_succeeded"] == 1
        assert run["adapters_failed"] == 0
        assert run["candidates_found"] == 5
        assert run["candidates_inserted"] == 5

    def test_update_discovery_run_with_error(self, db):
        """Update a FAILED run with error summary."""
        insert_discovery_run(
            db,
            run_id="run-003",
            started_at="2026-09-24T12:00:00Z",
            trigger="manual",
        )
        update_discovery_run(
            db,
            run_id="run-003",
            finished_at="2026-09-24T12:01:00Z",
            status="FAILED",
            adapters_total=1,
            adapters_succeeded=0,
            adapters_failed=1,
            candidates_found=0,
            candidates_inserted=0,
            candidates_duplicate=0,
            error_summary="Connection timeout after 3 retries",
        )
        run = get_discovery_run(db, "run-003")
        assert run is not None
        assert run["status"] == "FAILED"
        assert run["error_summary"] == "Connection timeout after 3 retries"

    def test_get_nonexistent_run_returns_none(self, db):
        """Getting a run that doesn't exist returns None."""
        result = get_discovery_run(db, "nonexistent")
        assert result is None

    def test_list_discovery_runs(self, db):
        """List discovery runs in reverse chronological order."""
        # Insert 3 runs
        for i in range(3):
            insert_discovery_run(
                db,
                run_id=f"list-run-{i}",
                started_at=f"2026-09-24T12:{i:02d}:00Z",
                trigger="manual",
            )

        runs = list_discovery_runs(db, limit=10)
        assert len(runs) == 3
        # Most recent first
        assert runs[0]["run_id"] == "list-run-2"
        assert runs[1]["run_id"] == "list-run-1"
        assert runs[2]["run_id"] == "list-run-0"

    def test_list_discovery_runs_with_limit(self, db):
        """List with limit truncates correctly."""
        for i in range(5):
            insert_discovery_run(
                db,
                run_id=f"limit-run-{i}",
                started_at=f"2026-09-24T12:{i:02d}:00Z",
                trigger="manual",
            )

        runs = list_discovery_runs(db, limit=2)
        assert len(runs) == 2

    def test_count_discovery_runs(self, db):
        """Count total discovery runs."""
        assert count_discovery_runs(db) == 0

        for i in range(3):
            insert_discovery_run(
                db,
                run_id=f"count-run-{i}",
                started_at=f"2026-09-24T12:{i:02d}:00Z",
            )

        assert count_discovery_runs(db) == 3

    def test_multiple_runs_coexist(self, db):
        """Multiple runs with different statuses can coexist."""
        insert_discovery_run(
            db, run_id="r1", started_at="2026-09-24T12:00:00Z"
        )
        insert_discovery_run(
            db, run_id="r2", started_at="2026-09-24T12:01:00Z"
        )

        update_discovery_run(
            db, run_id="r1", finished_at="2026-09-24T12:05:00Z",
            status="SUCCESS", adapters_total=1,
            adapters_succeeded=1, adapters_failed=0,
            candidates_found=10, candidates_inserted=10,
            candidates_duplicate=0,
        )
        update_discovery_run(
            db, run_id="r2", finished_at="2026-09-24T12:02:00Z",
            status="FAILED", adapters_total=1,
            adapters_succeeded=0, adapters_failed=1,
            candidates_found=0, candidates_inserted=0,
            candidates_duplicate=0,
            error_summary="Timeout",
        )

        r1 = get_discovery_run(db, "r1")
        r2 = get_discovery_run(db, "r2")
        assert r1["status"] == "SUCCESS"
        assert r2["status"] == "FAILED"


# ---------------------------------------------------------------------------
# insert_discovered_bounty tests
# ---------------------------------------------------------------------------

class TestInsertDiscoveredBounty:
    """Discovery-aware bounty insertion."""

    def test_insert_discovered_bounty_basic(self, db):
        """Insert a discovered bounty with discovery fields."""
        insert_discovered_bounty(
            db,
            id="disc-001",
            source="github",
            source_id="11276",
            canonical_issue_key="octocat/Hello-World#11276",
            title="Test Issue",
            description="A test issue",
            repository_url="https://github.com/octocat/Hello-World",
            issue_url="https://github.com/octocat/Hello-World/issues/11276",
            reward=None,
            currency=None,
            source_created_at="2026-09-24T03:23:43Z",
            source_updated_at="2026-09-24T03:23:43Z",
            last_activity="2026-09-24T03:23:43Z",
            state="open",
            labels=json.dumps(["bug", "good first issue"]),
            raw_payload_reference="github/abc123.json",
            raw_payload_hash="abc123def456",
            adapter_version="0.1.0",
            discovery_run_id="run-001",
        )
        row = db.connection.execute(
            "SELECT * FROM bounties WHERE id = ?",
            ("disc-001",),
        ).fetchone()
        assert row is not None
        assert row["source"] == "github"
        assert row["source_id"] == "11276"
        assert row["canonical_issue_key"] == "octocat/Hello-World#11276"
        assert row["title"] == "Test Issue"
        assert row["description"] == "A test issue"
        assert row["repository_url"] == "https://github.com/octocat/Hello-World"
        assert row["issue_url"] == "https://github.com/octocat/Hello-World/issues/11276"
        assert row["reward"] is None
        assert row["currency"] is None
        assert row["source_created_at"] == "2026-09-24T03:23:43Z"
        assert row["source_updated_at"] == "2026-09-24T03:23:43Z"
        assert row["last_activity"] == "2026-09-24T03:23:43Z"
        assert row["state"] == "open"
        assert json.loads(row["labels"]) == ["bug", "good first issue"]
        assert row["raw_payload_reference"] == "github/abc123.json"
        assert row["raw_payload_hash"] == "abc123def456"
        assert row["adapter_version"] == "0.1.0"
        assert row["discovery_run_id"] == "run-001"
        assert row["status"] == "discovered"

    def test_insert_discovered_bounty_nullable_fields(self, db):
        """Insert with minimal fields (nullable fields remain NULL)."""
        import datetime

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        insert_discovered_bounty(
            db,
            id="disc-002",
            source="github",
            source_id="9999",
            raw_payload_reference="github/minimal.json",
            raw_payload_hash="minimalhash",
            adapter_version="0.1.0",
            discovery_run_id="run-001",
        )
        row = db.connection.execute(
            "SELECT source, source_id, title, description, "
            "repository_url, issue_url, reward, currency, "
            "source_created_at, source_updated_at, last_activity, state, labels "
            "FROM bounties WHERE id = ?",
            ("disc-002",),
        ).fetchone()
        assert row["source"] == "github"
        assert row["source_id"] == "9999"
        assert row["title"] is None or row["title"] == ""
        assert row["description"] is None
        assert row["repository_url"] is None
        assert row["issue_url"] is None
        assert row["reward"] is None
        assert row["currency"] is None
        assert row["source_created_at"] is None
        assert row["source_updated_at"] is None
        assert row["last_activity"] is None
        assert row["state"] is None
        assert row["labels"] is None

    def test_insert_discovered_bounty_no_reward(self, db):
        """GitHub has no reward — reward and currency must be NULL."""
        insert_discovered_bounty(
            db,
            id="disc-003",
            source="github",
            source_id="5555",
            raw_payload_reference="github/noreward.json",
            raw_payload_hash="noreward",
            adapter_version="0.1.0",
            discovery_run_id="run-001",
            reward=None,
            currency=None,
        )
        row = db.connection.execute(
            "SELECT reward, currency FROM bounties WHERE id = ?",
            ("disc-003",),
        ).fetchone()
        assert row["reward"] is None
        assert row["currency"] is None

    def test_get_discovered_bounties_by_run(self, db):
        """Retrieve bounties discovered during a specific run."""
        insert_discovered_bounty(
            db,
            id="disc-r1-1",
            source="github",
            source_id="111",
            raw_payload_reference="github/a.json",
            raw_payload_hash="a",
            adapter_version="0.1.0",
            discovery_run_id="run-100",
        )
        insert_discovered_bounty(
            db,
            id="disc-r1-2",
            source="github",
            source_id="222",
            raw_payload_reference="github/b.json",
            raw_payload_hash="b",
            adapter_version="0.1.0",
            discovery_run_id="run-100",
        )
        insert_discovered_bounty(
            db,
            id="disc-r2-1",
            source="github",
            source_id="333",
            raw_payload_reference="github/c.json",
            raw_payload_hash="c",
            adapter_version="0.1.0",
            discovery_run_id="run-200",
        )

        bounties = get_discovered_bounties_by_run(db, "run-100")
        assert len(bounties) == 2
        ids = {b["id"] for b in bounties}
        assert "disc-r1-1" in ids
        assert "disc-r1-2" in ids
        assert "disc-r2-1" not in ids


# ---------------------------------------------------------------------------
# exists_source_source_id tests
# ---------------------------------------------------------------------------

class TestExistsSourceSourceId:
    """Dedup check: does (source, source_id) already exist?"""

    def test_nonexistent_returns_false(self, db):
        assert exists_source_source_id(db, "github", "nonexistent-123") is False

    def test_existing_returns_true(self, db):
        insert_discovered_bounty(
            db,
            id="dedup-001",
            source="github",
            source_id="12345",
            raw_payload_reference="github/d.json",
            raw_payload_hash="d",
            adapter_version="0.1.0",
            discovery_run_id="run-001",
        )
        assert exists_source_source_id(db, "github", "12345") is True

    def test_same_source_id_different_source(self, db):
        """Same source_id in different source is not a duplicate."""
        insert_discovered_bounty(
            db,
            id="dedup-a",
            source="github",
            source_id="123",
            raw_payload_reference="github/a.json",
            raw_payload_hash="a",
            adapter_version="0.1.0",
            discovery_run_id="run-001",
        )
        # Different source, same source_id — should NOT be a duplicate
        assert exists_source_source_id(db, "algora", "123") is False

    def test_same_source_different_source_id(self, db):
        """Same source, different source_id is not a duplicate."""
        insert_discovered_bounty(
            db,
            id="dedup-b",
            source="github",
            source_id="111",
            raw_payload_reference="github/b.json",
            raw_payload_hash="b",
            adapter_version="0.1.0",
            discovery_run_id="run-001",
        )
        assert exists_source_source_id(db, "github", "222") is False


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def row_is_none(value):
    """Check if a SQLite Row value is NULL."""
    return value is None
