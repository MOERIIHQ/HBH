"""
Tests for hbh.core.database — Phase 0.
"""

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
)
from hbh.core.state_machine import BountyStatus, record_transition, is_terminal
from hbh.core.audit import AuditLogger, log


@pytest.fixture
def temp_db_path(tmp_path):
    return str(tmp_path / "hbh_test.db")


@pytest.fixture
def config(tmp_path):
    return load_config(
        hbhome=str(tmp_path),
        db_path=str(tmp_path / "hbh_test.db"),
        policy_path=str(tmp_path / "config" / "default_policy.yaml"),
    )


@pytest.fixture
def db(config, temp_db_path):
    cfg = load_config(
        hbhome=config.home,
        db_path=temp_db_path,
        policy_path=config.policy_path,
    )
    database = Database.create(cfg)
    ensure_schema(database)
    yield database
    database.close()


class TestDatabaseCreation:
    def test_creates_sqlite_file(self, config, temp_db_path):
        db = Database.create(config)
        assert os.path.exists(temp_db_path)
        db.close()

    def test_connection_object_returned(self, config, temp_db_path):
        db = Database.create(config)
        assert db.connection is not None
        assert db.path == temp_db_path
        db.close()


class TestSchemaCreation:
    def test_schema_v3_applied(self, db):
        version = current_schema_version(db)
        assert version == 3

    def test_idempotent_initialization(self, db, temp_db_path):
        # Second call should not fail
        cfg = load_config(
            hbhome=db.path.rsplit("hbh_test.db", 1)[0],
            db_path=temp_db_path,
            policy_path="dummy",
        )
        db2 = Database.create(cfg)
        ensure_schema(db2)
        version = current_schema_version(db2)
        assert version == 3
        db2.close()


class TestSchemaVersion:
    def test_uninitialized_has_version_zero(self, tmp_path):
        path = str(tmp_path / "fresh.db")
        cfg = load_config(db_path=path, hbhome=str(tmp_path))
        db = Database.create(cfg)
        assert current_schema_version(db) == 0
        assert not is_initialized(db)
        db.close()

    def test_after_ensure_schema_version_is_correct(self, db):
        assert current_schema_version(db) == 3
        assert is_initialized(db)


class TestSchemaVersionFailClosed:
    def test_unsupported_version_raises(self, tmp_path, monkeypatch):
        path = str(tmp_path / "bad_schema.db")
        cfg = load_config(db_path=path, hbhome=str(tmp_path))

        # Manually create a DB with version 4 (unsupported)
        import sqlite3
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE schema_versions (version INTEGER PRIMARY KEY, applied_at TEXT)")
        conn.execute("INSERT INTO schema_versions (version, applied_at) VALUES (4, '2026-01-01T00:00:00')")
        conn.commit()
        conn.close()

        db = Database.connect(path)
        with pytest.raises(SchemaMismatchError, match="not supported"):
            validate_schema_version(db)
        db.close()


class TestRequiredTables:
    def test_bounties_table_exists(self, db):
        row = db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='bounties'"
        ).fetchone()
        assert row is not None

    def test_repositories_table_exists(self, db):
        row = db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='repositories'"
        ).fetchone()
        assert row is not None

    def test_triage_table_exists(self, db):
        row = db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='triage'"
        ).fetchone()
        assert row is not None

    def test_executions_table_exists(self, db):
        row = db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='executions'"
        ).fetchone()
        assert row is not None

    def test_outcomes_table_exists(self, db):
        row = db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='outcomes'"
        ).fetchone()
        assert row is not None

    def test_events_table_exists(self, db):
        row = db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='events'"
        ).fetchone()
        assert row is not None

    def test_schema_versions_table_exists(self, db):
        row = db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_versions'"
        ).fetchone()
        assert row is not None


class TestCRUD:
    def test_insert_bounty(self, db):
        insert_bounty(db, id="b-1", platform="github", url="https://example.com", title="Test", status="discovered")
        assert count_bounties(db) == 1

    def test_insert_event(self, db):
        eid = insert_event(
            db,
            entity_id="b-1",
            actor="system",
            reason="test_event",
            from_state="discovered",
            to_state="profiled",
            metadata={"key": "value"},
        )
        assert eid > 0
        row = db.connection.execute(
            "SELECT * FROM events WHERE event_id = ?", (eid,)
        ).fetchone()
        assert row["entity_id"] == "b-1"
        assert row["actor"] == "system"
        assert row["from_state"] == "discovered"
        assert row["to_state"] == "profiled"
        assert row["metadata"] == json.dumps({"key": "value"})


class TestAuditIntegration:
    def test_record_transition_emits_event(self, db, tmp_path):
        cfg = load_config(
            hbhome=str(tmp_path),
            db_path=db.path,
            policy_path="dummy",
        )
        logger = AuditLogger(cfg)

        transition = record_transition(
            logger,
            entity_id="b-1",
            actor="system",
            from_state=BountyStatus.DISCOVERED,
            to_state=BountyStatus.PROFILED,
            reason="profile_started",
            db=db,
        )

        assert transition.to_state == BountyStatus.PROFILED

        row = db.connection.execute(
            "SELECT * FROM events ORDER BY event_id DESC LIMIT 1"
        ).fetchone()
        assert row["entity_id"] == "b-1"
        assert row["actor"] == "system"
        assert row["from_state"] == "discovered"
        assert row["to_state"] == "profiled"
        assert row["reason"] == "profile_started"
