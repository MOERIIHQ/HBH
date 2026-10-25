"""
Regression tests for hbh.discovery.repository_profiler_integration
--- RP-2 persistence correction for record_profile_run().

Covers the mapping repositories.profile_status <- profile_runs.status per
contract §7.2/§7.3, the FAILED-without-RepositoryProfile-with-identity
path, fail-closed for missing identity and missing repository row, and
atomic transaction / rollback behaviour.

Unit A/B/C tests are untouched.
"""

import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))

from hbh.core.config import load_config
from hbh.core.database import Database, ensure_schema, current_schema_version, insert_event
from hbh.discovery.profile import (
    ProfileResult,
    ProfileStatus,
    RepositoryIdentity,
    make_profile_result,
    make_repository_profile,
)
from hbh.discovery.repository_profiler_integration import record_profile_run


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


def _insert_repository(db, repo_id, owner, name):
    db.connection.execute(
        "INSERT INTO repositories (repo_id, owner, name, profile_status) VALUES (?, ?, ?, ?)",
        (repo_id, owner, name, "pending"),
    )


def _repo_status(db, repo_id):
    row = db.connection.execute(
        "SELECT profile_status FROM repositories WHERE repo_id = ?", (repo_id,)
    ).fetchone()
    return row["profile_status"] if row is not None else None


def _make_identity(**overrides):
    defaults = dict(
        source="github",
        repository="owner/repo",
        canonical_url="https://github.com/owner/repo",
        owner="owner",
        name="repo",
    )
    defaults.update(overrides)
    return RepositoryIdentity(**defaults)


@pytest.fixture
def identity():
    return RepositoryIdentity(
        source="github",
        repository="owner/repo",
        canonical_url="https://github.com/owner/repo",
        owner="owner",
        name="repo",
    )


@pytest.fixture
def repo_profile(identity):
    return make_repository_profile(
        source=identity.source,
        owner=identity.owner,
        name=identity.name,
        profile_run_id="run-001",
        profiled_at="2026-01-01T00:00:00+00:00",
    )


class TestSuccess:
    def test_success_updates_status_to_profiled(self, db, repo_profile):
        repo_id = f"github:{repo_profile.owner}/{repo_profile.name}"
        _insert_repository(db, repo_id, repo_profile.owner, repo_profile.name)
        db.connection.commit()

        result = record_profile_run(
            db,
            make_profile_result(ProfileStatus.SUCCESS, profile=repo_profile),
            "run-success",
        )
        assert result is True
        assert _repo_status(db, repo_id) == "profiled"

    def test_success_preserves_previous_run_history(self, db, repo_profile):
        repo_id = f"github:{repo_profile.owner}/{repo_profile.name}"
        _insert_repository(db, repo_id, repo_profile.owner, repo_profile.name)
        db.connection.commit()
        db.connection.execute(
            "INSERT INTO repository_profiles "
            "(profile_run_id, discovery_run_id, source, repository, "
            "canonical_url, owner, name, profiled_at, source_endpoint, "
            "adapter_version, raw_payload_reference, raw_payload_hash, "
            "status, profile_data, created_at) "
            "VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "run-prev",
                "github",
                "owner/repo",
                "https://github.com/owner/repo",
                "owner",
                "repo",
                "2026-01-01T00:00:00+00:00",
                "/repos/owner/repo",
                "1.0.0",
                None,
                None,
                "SUCCESS",
                "{}",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        db.connection.execute(
            "INSERT INTO profile_runs "
            "(profile_run_id, discovery_run_id, start_profiling_at, "
            "end_profiling_at, status, error_summary, repository_count) "
            "VALUES (?, NULL, NULL, ?, ?, ?, ?)",
            (
                "run-prev",
                "2026-01-01T00:00:01+00:00",
                "SUCCESS",
                "previous run succeeded",
                1,
            ),
        )

        result = record_profile_run(
            db,
            make_profile_result(ProfileStatus.SUCCESS, profile=repo_profile),
            "run-new",
        )
        assert result is True
        count = db.connection.execute(
            "SELECT COUNT(*) AS n FROM repository_profiles"
        ).fetchone()["n"]
        assert count >= 2


class TestPartial:
    def test_partial_updates_status_to_partial(self, db, repo_profile):
        repo_id = f"github:{repo_profile.owner}/{repo_profile.name}"
        _insert_repository(db, repo_id, repo_profile.owner, repo_profile.name)
        db.connection.commit()

        result = record_profile_run(
            db,
            make_profile_result(ProfileStatus.PARTIAL, profile=repo_profile),
            "run-partial",
        )
        assert result is True
        assert _repo_status(db, repo_id) == "partial"


class TestFailedWithoutProfileWithIdentity:
    def test_failed_without_profile_updates_status_to_failed(self, db, identity):
        repo_id = f"{identity.source}:{identity.owner}/{identity.name}"
        _insert_repository(db, repo_id, identity.owner, identity.name)

        result = record_profile_run(
            db,
            make_profile_result(ProfileStatus.FAILED, profile=None),
            "run-failed-no-profile",
            repository_identity=identity,
        )
        assert result is True
        assert _repo_status(db, repo_id) == "failed"

    def test_failed_without_profile_retains_previous_run_history(self, db, identity):
        repo_id = f"{identity.source}:{identity.owner}/{identity.name}"
        _insert_repository(db, repo_id, identity.owner, identity.name)
        db.connection.execute(
            "INSERT INTO repository_profiles "
            "(profile_run_id, discovery_run_id, source, repository, "
            "canonical_url, owner, name, profiled_at, source_endpoint, "
            "adapter_version, raw_payload_reference, raw_payload_hash, "
            "status, profile_data, created_at) "
            "VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "run-prev",
                "github",
                "owner/repo",
                "https://github.com/owner/repo",
                "owner",
                "repo",
                "2026-01-01T00:00:00+00:00",
                "/repos/owner/repo",
                "1.0.0",
                None,
                None,
                "SUCCESS",
                "{}",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        db.connection.execute(
            "INSERT INTO profile_runs "
            "(profile_run_id, discovery_run_id, start_profiling_at, "
            "end_profiling_at, status, error_summary, repository_count) "
            "VALUES (?, NULL, NULL, ?, ?, ?, ?)",
            (
                "run-prev",
                "2026-01-01T00:00:01+00:00",
                "SUCCESS",
                "previous run succeeded",
                1,
            ),
        )

        result = record_profile_run(
            db,
            make_profile_result(ProfileStatus.FAILED, profile=None),
            "run-failed-no-profile",
            repository_identity=identity,
        )
        assert result is True
        assert _repo_status(db, repo_id) == "failed"
        total = db.connection.execute(
            "SELECT COUNT(*) AS n FROM repository_profiles"
        ).fetchone()["n"]
        assert total >= 2


class TestIdentityUnavailable:
    def test_identity_unavailable_fails_closed(self, db):
        result = record_profile_run(
            db,
            make_profile_result(ProfileStatus.FAILED, profile=None),
            "run-no-identity",
        )
        assert result is False
        count = db.connection.execute(
            "SELECT COUNT(*) AS n FROM repository_profiles"
        ).fetchone()["n"]
        assert count == 0
        count2 = db.connection.execute(
            "SELECT COUNT(*) AS n FROM repositories"
        ).fetchone()["n"]
        assert count2 == 0


class TestRepositoryNotFound:
    def test_missing_repository_row_fails_closed(self, db, identity):
        result = record_profile_run(
            db,
            make_profile_result(ProfileStatus.FAILED, profile=None),
            "run-missing-repo",
            repository_identity=identity,
        )
        assert result is False
        count = db.connection.execute(
            "SELECT COUNT(*) AS n FROM repository_profiles"
        ).fetchone()["n"]
        assert count == 0


class TestPersistenceFailure:
    def test_insert_failure_rolls_back(self, db, repo_profile):
        repo_id = f"github:{repo_profile.owner}/{repo_profile.name}"
        _insert_repository(db, repo_id, repo_profile.owner, repo_profile.name)
        db.connection.commit()

        bad_run_id = ""
        db.connection.commit()
        # Simulate a PK conflict: insert a row with the same profile_run_id first.
        # Insert conflicting row to simulate PK violation
        db.connection.execute(
            "INSERT INTO repository_profiles "
            "(profile_run_id, discovery_run_id, source, repository, canonical_url, "\
            "owner, name, profiled_at, source_endpoint, adapter_version, "\
            "raw_payload_reference, raw_payload_hash, "
            "status, profile_data, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                bad_run_id,
                "github",
                "owner/repo",
                "https://github.com/owner/repo",
                "owner",
                "repo",
                "2026-01-01T00:00:00+00:00",
                "/repos/owner/repo",
                "1.0.0",
                None,
                None,
                "SUCCESS",
                "{}",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        result = record_profile_run(
            db,
            make_profile_result(ProfileStatus.SUCCESS, profile=repo_profile),
            bad_run_id,
        )
        assert result is False
        count = db.connection.execute(
            "SELECT COUNT(*) AS n FROM repository_profiles WHERE profile_run_id = ?",
            (bad_run_id,),
        ).fetchone()["n"]
        assert count == 0
        assert _repo_status(db, repo_id) == "pending"



class TestIdentityConflict:
    def test_conflicting_identity_fails_closed(self, db, identity, repo_profile):
        repo_id = f"{identity.source}:{identity.owner}/{identity.name}"
        _insert_repository(db, repo_id, repo_profile.owner, repo_profile.name)
        db.connection.commit()
        db.connection.commit()

        conflicting_identity = RepositoryIdentity(
            source="github",
            repository="other_owner/other_repo",
            owner="other_owner",
            name="other_repo",
            canonical_url="https://github.com/other_owner/other_repo",
        )

        result = record_profile_run(
            db,
            make_profile_result(ProfileStatus.SUCCESS, profile=repo_profile),
            "run-conflict",
            repository_identity=conflicting_identity,
        )
        assert result is False
        count = db.connection.execute(
            "SELECT COUNT(*) AS n FROM repository_profiles WHERE profile_run_id = 'run-conflict'"
        ).fetchone()["n"]
        assert count == 0
        status = _repo_status(db, repo_id)
        assert status == "pending"

    def test_identity_matches_profile_and_repo_row(self, db, identity, repo_profile):
        repo_id = f"{identity.source}:{identity.owner}/{identity.name}"
        _insert_repository(db, repo_id, repo_profile.owner, repo_profile.name)
        db.connection.commit()

        result = record_profile_run(
            db,
            make_profile_result(ProfileStatus.SUCCESS, profile=repo_profile),
            "run-match",
            repository_identity=identity,
        )
        assert result is True
        assert _repo_status(db, repo_id) == "profiled"


class TestPostCommitAuditFailure:
    def test_post_commit_audit_failure_does_not_affect_persistence(self, db, repo_profile):
        repo_id = f"github:{repo_profile.owner}/{repo_profile.name}"
        _insert_repository(db, repo_id, repo_profile.owner, repo_profile.name)
        db.connection.commit()

        audit_failure = {"raised": False}

        def failing_hook():
            audit_failure["raised"] = True
            raise RuntimeError("Audit hook failed")

        result = record_profile_run(
            db,
            make_profile_result(ProfileStatus.SUCCESS, profile=repo_profile),
            "run-audit-fail",
            post_commit_hooks=[failing_hook],
        )
        assert result is True
        count = db.connection.execute(
            "SELECT COUNT(*) AS n FROM repository_profiles WHERE profile_run_id = 'run-audit-fail'"
        ).fetchone()["n"]
        assert count == 1
        assert _repo_status(db, repo_id) == "profiled"
        assert audit_failure["raised"] is True


class TestSchemaCompatibility:
    def test_schema_version_is_three(self, db):
        version = current_schema_version(db)
        assert version == 3

    def test_repository_profiles_table_exists(self, db):
        row = db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='repository_profiles'"
        ).fetchone()
        assert row is not None

    def test_profile_runs_table_exists(self, db):
        row = db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='profile_runs'"
        ).fetchone()
        assert row is not None


class TestAuditEvents:
    """Event profiling recording for SUCCESS / PARTIAL / FAILED runs (contract 5)."""

    def test_success_event_emitted(self, db, repo_profile, capsys):
        repo_id = f"github:{repo_profile.owner}/{repo_profile.name}"
        _insert_repository(db, repo_id, repo_profile.owner, repo_profile.name)
        db.connection.commit()
        profile_run_id = "run-success-aud"
        record_profile_run(db, make_profile_result(ProfileStatus.SUCCESS, profile=repo_profile), profile_run_id)
        rows = db.connection.execute(
            "SELECT actor, reason FROM events WHERE entity_id = ? ORDER BY rowid",
            (profile_run_id,),
        ).fetchall()
        assert len(rows) == 3
        assert rows[0]["actor"] == "repository_profiler_integration"
        assert rows[0]["reason"] == "profil run dimulai"
        assert rows[1]["actor"] == "repository_profiler_integration"
        assert rows[1]["reason"] == "profil selesai (SUCCESS/PARTIAL)"
        assert rows[2]["actor"] == "database_integration"
        assert rows[2]["reason"] == "data profil tersimpan"
        captured = capsys.readouterr()
        assert "profile_run_started" in captured.err
        assert "profile_run_completed" in captured.err
        assert "profile_persisted" in captured.err

    def test_partial_event_emitted(self, db, repo_profile, capsys):
        repo_id = f"github:{repo_profile.owner}/{repo_profile.name}"
        _insert_repository(db, repo_id, repo_profile.owner, repo_profile.name)
        db.connection.commit()
        profile_run_id = "run-partial-aud"
        record_profile_run(db, make_profile_result(ProfileStatus.PARTIAL, profile=repo_profile), profile_run_id)
        rows = db.connection.execute(
            "SELECT actor, reason FROM events WHERE entity_id = ? ORDER BY rowid",
            (profile_run_id,),
        ).fetchall()
        assert len(rows) == 3
        assert rows[0]["reason"] == "profil run dimulai"
        assert rows[1]["reason"] == "profil selesai (SUCCESS/PARTIAL)"
        assert rows[2]["reason"] == "data profil tersimpan"
        captured = capsys.readouterr()
        assert "profile_run_started" in captured.err
        assert "profile_run_completed" in captured.err
        assert "profile_persisted" in captured.err
        row = db.connection.execute("SELECT status FROM profile_runs WHERE profile_run_id = ?", (profile_run_id,)).fetchone()
        assert row["status"] == "PARTIAL"

    def test_failed_event_emitted(self, db, identity, capsys):
        repo_id = f"{identity.source}:{identity.owner}/{identity.name}"
        _insert_repository(db, repo_id, identity.owner, identity.name)
        db.connection.commit()
        profile_run_id = "run-failed-aud"
        record_profile_run(db, make_profile_result(ProfileStatus.FAILED, profile=None), profile_run_id, repository_identity=identity)
        rows = db.connection.execute(
            "SELECT actor, reason FROM events WHERE entity_id = ? ORDER BY rowid",
            (profile_run_id,),
        ).fetchall()
        assert len(rows) == 3
        assert rows[0]["reason"] == "profil run dimulai"
        assert rows[1]["reason"] == "profil gagal"
        assert rows[2]["reason"] == "data profil tersimpan"
        captured = capsys.readouterr()
        assert "profile_run_started" in captured.err
        assert "profile_run_failed" in captured.err
        assert "profile_persisted" in captured.err
        row = db.connection.execute("SELECT status FROM profile_runs WHERE profile_run_id = ?", (profile_run_id,)).fetchone()
        assert row["status"] == "FAILED"
        assert _repo_status(db, repo_id) == "failed"

    def test_event_actor_and_entity_id(self, db, repo_profile, capsys):
        repo_id = f"github:{repo_profile.owner}/{repo_profile.name}"
        _insert_repository(db, repo_id, repo_profile.owner, repo_profile.name)
        db.connection.commit()
        profile_run_id = "run-actor-aud"
        record_profile_run(db, make_profile_result(ProfileStatus.SUCCESS, profile=repo_profile), profile_run_id)
        rows = db.connection.execute(
            "SELECT actor, entity_id, reason FROM events WHERE entity_id = ? ORDER BY rowid",
            (profile_run_id,),
        ).fetchall()
        assert rows[0]["actor"] == "repository_profiler_integration"
        assert rows[0]["entity_id"] == profile_run_id
        assert rows[0]["reason"] == "profil run dimulai"
        assert rows[1]["actor"] == "repository_profiler_integration"
        assert rows[1]["entity_id"] == profile_run_id
        assert rows[1]["reason"] == "profil selesai (SUCCESS/PARTIAL)"
        assert rows[2]["actor"] == "database_integration"
        assert rows[2]["entity_id"] == profile_run_id
        assert rows[2]["reason"] == "data profil tersimpan"

    def test_insert_event_not_called_while_main_tx_open(self, db, monkeypatch):
        # Pre-open a main transaction; while it is open, insert_event() must NOT
        # be called for the profiling events (only stderr). After COMMIT,
        # completed + persisted are recorded.
        db.connection.execute("BEGIN")
        calls = []
        original_insert_event = insert_event
        def tracked_insert(*a, **k):
            calls.append(True)
            return original_insert_event(*a, **k)
        monkeypatch.setattr("hbh.discovery.repository_profiler_integration.insert_event", tracked_insert)
        repo_profile = make_repository_profile(profile_run_id="run-txopen")
        repo_id = f"github:{repo_profile.owner}/{repo_profile.name}"
        _insert_repository(db, repo_id, repo_profile.owner, repo_profile.name)
        result = record_profile_run(db, make_profile_result(ProfileStatus.SUCCESS, profile=repo_profile), "run-txopen")
        assert result is True
        assert len(calls) == 2
        assert db.connection.execute("SELECT COUNT(*) AS n FROM events WHERE entity_id = 'run-txopen'").fetchone()["n"] == 2

    def test_persistence_failure_rolls_back_no_success(self, db, repo_profile):
        repo_id = f"github:{repo_profile.owner}/{repo_profile.name}"
        _insert_repository(db, repo_id, repo_profile.owner, repo_profile.name)
        db.connection.commit()
        conflict_run_id = "run-persist-fail"
        db.connection.execute(
            "INSERT INTO repository_profiles (profile_run_id, discovery_run_id, source, repository, canonical_url, owner, name, profiled_at, source_endpoint, adapter_version, raw_payload_reference, raw_payload_hash, status, profile_data, created_at) "
            "VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                conflict_run_id, "github", "owner/repo", "https://github.com/owner/repo", "owner", "repo",
                "2026-01-01T00:00:00+00:00", "/repos/owner/repo", "1.0.0", None, None, "SUCCESS", "{}", "2026-01-01T00:00:00+00:00",
            ),
        )
        result = record_profile_run(db, make_profile_result(ProfileStatus.SUCCESS, profile=repo_profile), conflict_run_id)
        assert result is False
        assert db.connection.execute("SELECT COUNT(*) AS n FROM repository_profiles WHERE profile_run_id = ?", (conflict_run_id,)).fetchone()["n"] == 0
        assert db.connection.execute("SELECT COUNT(*) AS n FROM profile_runs WHERE profile_run_id = ?", (conflict_run_id,)).fetchone()["n"] == 0
        assert _repo_status(db, repo_id) == "pending"

    def test_audit_failure_after_commit_does_not_change_persistence(self, db, repo_profile, monkeypatch, capsys):
        repo_id = f"github:{repo_profile.owner}/{repo_profile.name}"
        _insert_repository(db, repo_id, repo_profile.owner, repo_profile.name)
        db.connection.commit()
        def failing_insert(*a, **k):
            raise RuntimeError("events table insert failed")
        monkeypatch.setattr("hbh.discovery.repository_profiler_integration.insert_event", failing_insert)
        result = record_profile_run(db, make_profile_result(ProfileStatus.SUCCESS, profile=repo_profile), "run-audit-sqlite-fail")
        assert result is True
        assert db.connection.execute("SELECT COUNT(*) AS n FROM profile_runs WHERE profile_run_id = ?", ("run-audit-sqlite-fail",)).fetchone()["n"] == 1
        assert _repo_status(db, repo_id) == "profiled"
        captured = capsys.readouterr()
        assert "audit_error" in captured.err

    def test_audit_failure_after_rollback_does_not_mask_persistence_failure(self, db, repo_profile, monkeypatch, capsys):
        repo_id = f"github:{repo_profile.owner}/{repo_profile.name}"
        _insert_repository(db, repo_id, repo_profile.owner, repo_profile.name)
        db.connection.commit()
        def failing_insert(*a, **k):
            raise RuntimeError("events table insert failed")
        monkeypatch.setattr("hbh.discovery.repository_profiler_integration.insert_event", failing_insert)
        conflict_run_id = "run-rollback-audit-fail"
        db.connection.execute(
            "INSERT INTO repository_profiles (profile_run_id, discovery_run_id, source, repository, canonical_url, owner, name, profiled_at, source_endpoint, adapter_version, raw_payload_reference, raw_payload_hash, status, profile_data, created_at) "
            "VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                conflict_run_id, "github", "owner/repo", "https://github.com/owner/repo", "owner", "repo",
                "2026-01-01T00:00:00+00:00", "/repos/owner/repo", "1.0.0", None, None, "SUCCESS", "{}", "2026-01-01T00:00:00+00:00",
            ),
        )
        result = record_profile_run(db, make_profile_result(ProfileStatus.SUCCESS, profile=repo_profile), conflict_run_id)
        assert result is False
        assert db.connection.execute("SELECT COUNT(*) AS n FROM repository_profiles WHERE profile_run_id = ?", (conflict_run_id,)).fetchone()["n"] == 0
        assert _repo_status(db, repo_id) == "pending"
        captured = capsys.readouterr()
        assert "audit_error" in captured.err

    def test_stderr_failure_does_not_change_persistence(self, db, repo_profile):
        repo_id = f"github:{repo_profile.owner}/{repo_profile.name}"
        _insert_repository(db, repo_id, repo_profile.owner, repo_profile.name)
        db.connection.commit()
        original_stderr = sys.stderr
        class FailingStderr:
            def write(self, s):
                raise OSError("broken pipe")
            def flush(self):
                raise OSError("broken pipe")
        sys.stderr = FailingStderr()
        try:
            result = record_profile_run(db, make_profile_result(ProfileStatus.SUCCESS, profile=repo_profile), "run-stderr-fail")
            assert result is True
            assert db.connection.execute("SELECT COUNT(*) AS n FROM profile_runs WHERE profile_run_id = ?", ("run-stderr-fail",)).fetchone()["n"] == 1
            assert _repo_status(db, repo_id) == "profiled"
        finally:
            sys.stderr = original_stderr

    def test_no_duplicate_event_for_one_run(self, db, repo_profile, capsys):
        repo_id = f"github:{repo_profile.owner}/{repo_profile.name}"
        _insert_repository(db, repo_id, repo_profile.owner, repo_profile.name)
        db.connection.commit()
        profile_run_id = "run-no-dup"
        record_profile_run(db, make_profile_result(ProfileStatus.SUCCESS, profile=repo_profile), profile_run_id)
        rows = db.connection.execute(
            "SELECT COUNT(*) AS n FROM events WHERE entity_id = ?", (profile_run_id,)
        ).fetchone()["n"]
        assert rows == 3
        captured = capsys.readouterr()
        for event_name in ("profile_run_started", "profile_run_completed", "profile_persisted"):
            assert event_name in captured.err, event_name
