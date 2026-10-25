"""
Tests for hbh.discovery.raw_storage — Phase 1b-GH-2B.

Focused tests for raw evidence storage, hash verification, path safety,
tamper detection, deduplication, and edge cases.
"""

from __future__ import annotations

import json
import os
import tempfile
import pytest

from hbh.discovery.raw_storage import (
    EvidenceIntegrityError,
    RawStorage,
    RawStorageError,
    UnsafeSourceError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def storage_root(tmp_path):
    root = str(tmp_path / "raw")
    os.makedirs(root, exist_ok=True)
    yield root


@pytest.fixture
def storage(storage_root):
    return RawStorage(storage_root)


# ---------------------------------------------------------------------------
# Basic storage
# ---------------------------------------------------------------------------

class TestBasicStorage:
    def test_store_creates_file(self, storage):
        payload = {"key": "value"}
        rel_path, content_hash = storage.store("test", payload)
        full = os.path.join(storage.root, rel_path)
        assert os.path.isfile(full)

    def test_stored_file_is_valid_json(self, storage):
        payload = {"title": "Test", "body": "Hello"}
        rel_path, _ = storage.store("test", payload)
        full = os.path.join(storage.root, rel_path)
        with open(full, "rb") as fh:
            data = json.loads(fh.read())
        assert data["title"] == "Test"
        assert data["body"] == "Hello"

    def test_store_returns_relative_path(self, storage):
        rel_path, content_hash = storage.store("test", {"x": 1})
        assert rel_path == "test/" + content_hash + ".json"

    def test_store_returns_sha256_hex(self, storage):
        _, content_hash = storage.store("test", {"x": 1})
        assert len(content_hash) == 64
        assert all(c in "0123456789abcdef" for c in content_hash)

    def test_empty_payload(self, storage):
        rel_path, content_hash = storage.store("test", {})
        full = os.path.join(storage.root, rel_path)
        assert os.path.isfile(full)
        with open(full, "rb") as fh:
            assert fh.read() == b"{}"


# ---------------------------------------------------------------------------
# Hash correctness
# ---------------------------------------------------------------------------

class TestHash:
    def test_stored_bytes_hash_matches_recorded(self, storage):
        payload = {"issue": "test", "state": "open"}
        _, content_hash = storage.store("github", payload)
        rel_path = "github/" + content_hash + ".json"
        full = os.path.join(storage.root, rel_path)
        with open(full, "rb") as fh:
            actual = fh.read()
        import hashlib
        assert hashlib.sha256(actual).hexdigest() == content_hash

    def test_hash_is_deterministic_same_payload(self, storage):
        payload = {"a": 1, "b": 2}
        _, h1 = storage.store("src", payload)
        _, h2 = storage.store("src", payload)
        assert h1 == h2

    def test_different_payload_different_hash(self, storage):
        _, h1 = storage.store("src", {"a": 1})
        _, h2 = storage.store("src", {"a": 2})
        assert h1 != h2


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_same_content_same_file(self, storage):
        payload = {"foo": "bar"}
        rel1, h1 = storage.store("ns", payload)
        rel2, h2 = storage.store("ns", payload)
        assert rel1 == rel2
        assert h1 == h2
        # Only one file on disk
        files = os.listdir(os.path.join(storage.root, "ns"))
        assert len(files) == 1

    def test_canonical_key_order(self, storage):
        # Dict with different insertion order should produce same bytes.
        p1 = {"b": 2, "a": 1}
        p2 = {"a": 1, "b": 2}
        _, h1 = storage.store("ns", p1)
        _, h2 = storage.store("ns", p2)
        assert h1 == h2


# ---------------------------------------------------------------------------
# Integrity / tamper detection
# ---------------------------------------------------------------------------

class TestIntegrity:
    def test_verify_returns_true_for_intact_file(self, storage):
        _, content_hash = storage.store("github", {"ok": True})
        rel_path = "github/" + content_hash + ".json"
        assert storage.verify(rel_path, content_hash) is True

    def test_verify_returns_false_for_missing_file(self, storage):
        assert storage.verify("github/missing.json", "abc") is False

    def test_verify_returns_false_for_wrong_hash(self, storage):
        _, content_hash = storage.store("github", {"ok": True})
        rel_path = "github/" + content_hash + ".json"
        assert storage.verify(rel_path, "wronghash") is False

    def test_tamper_detection(self, storage):
        payload = {"data": "original"}
        _, content_hash = storage.store("github", payload)
        rel_path = "github/" + content_hash + ".json"
        full = os.path.join(storage.root, rel_path)

        # Tamper with the file
        with open(full, "ab") as fh:
            fh.write(b"tampered")

        assert storage.verify(rel_path, content_hash) is False


# ---------------------------------------------------------------------------
# Duplicate handling
# ---------------------------------------------------------------------------

class TestDuplicatePayload:
    def test_duplicate_does_not_corrupt(self, storage):
        payload = {"id": 42}
        rel1, h1 = storage.store("src", payload)
        rel2, h2 = storage.store("src", payload)
        assert rel1 == rel2
        assert h1 == h2

    def test_different_payloads_different_files(self, storage):
        rel1, h1 = storage.store("src", {"a": 1})
        rel2, h2 = storage.store("src", {"b": 2})
        assert h1 != h2
        assert rel1 != rel2

    def test_integrity_conflict_raises(self, storage):
        # Store a payload, then manually create a file with the same name
        # but different content to trigger EvidenceIntegrityError.
        payload = {"x": 1}
        _, content_hash = storage.store("src", payload)

        # Overwrite with different content directly (simulating corruption)
        rel_path = "src/" + content_hash + ".json"
        full = os.path.join(storage.root, rel_path)
        with open(full, "wb") as fh:
            fh.write(b'{"x": 2}')

        with pytest.raises(EvidenceIntegrityError):
            storage.store("src", {"x": 1})


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------

class TestPathSafety:
    def test_normalshallow_source(self, storage):
        rel_path, _ = storage.store("github", {"ok": True})
        assert rel_path.startswith("github/")

    def test_updir_traversal_rejected(self, storage):
        with pytest.raises(UnsafeSourceError):
            storage.store("../outside", {"x": 1})

    def test_deep_updir_traversal_rejected(self, storage):
        with pytest.raises(UnsafeSourceError):
            storage.store("../../outside", {"x": 1})

    def test_absolute_path_rejected(self, storage):
        with pytest.raises(UnsafeSourceError):
            storage.store("/etc/passwd", {"x": 1})

    def test_tilde_rejected(self, storage):
        with pytest.raises(UnsafeSourceError):
            storage.store("~/evil", {"x": 1})

    def test_valid_source_with_dots_allowed(self, storage):
        # "source.with.dots" — dots are allowed in the middle.
        rel_path, _ = storage.store("source.with.dots", {"ok": True})
        assert "source.with.dots" in rel_path

    def test_file_outside_root_not_reachable_via_verify(self, storage):
        # Even if someone crafts a relative path with .., verify must
        # refuse to read outside the root.
        assert storage.verify("../escape.json", "abc") is False


# ---------------------------------------------------------------------------
# Directory creation and idempotency
# ---------------------------------------------------------------------------

class TestDirectoryCreation:
    def test_creates_source_directory(self, tmp_path):
        root = str(tmp_path / "raw")
        os.makedirs(root, exist_ok=True)
        storage = RawStorage(root)
        storage.store("new_source", {"x": 1})
        assert os.path.isdir(os.path.join(root, "new_source"))

    def test_existing_directory_is_safe(self, storage):
        # Calling store multiple times on the same source should be safe.
        payload = {"count": 1}
        for _ in range(5):
            storage.store("repeated", payload)
        files = os.listdir(os.path.join(storage.root, "repeated"))
        assert len(files) == 1  # dedup keeps one file

    def test_root_created_if_missing(self, tmp_path):
        root = str(tmp_path / "nonexistent" / "raw")
        storage = RawStorage(root)
        assert os.path.isdir(root)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_non_serializable_payload_raises_typeerror(self, storage):
        """GH-2B corrective: non-JSON-serializable objects must raise,
        not be silently converted via str()."""
        import datetime
        payload = {"timestamp": datetime.datetime(2026, 1, 1, 0, 0, 0)}
        with pytest.raises(TypeError):
            storage.store("test", payload)

    def test_source_rejects_empty_string(self, storage):
        with pytest.raises(UnsafeSourceError):
            storage.store("", {"x": 1})

    def test_source_rejects_none(self, storage):
        with pytest.raises(UnsafeSourceError):
            storage.store(None, {"x": 1})

    def test_source_max_length(self, storage):
        long_source = "a" * 200
        with pytest.raises(UnsafeSourceError):
            storage.store(long_source, {"x": 1})


# ---------------------------------------------------------------------------
# Integration: engine + raw storage
# ---------------------------------------------------------------------------

class TestEngineRawStorageIntegration:
    def test_candidate_persists_with_raw_evidence_from_source_payload(self, tmp_path):
        """GH-2B corrective: raw evidence must represent the SOURCE payload,
        not a normalized BountyCandidate reconstruction."""
        from hbh.core.config import Config
        from hbh.core.database import Database, ensure_schema
        from hbh.discovery.engine import create_discovery_engine
        from hbh.discovery.models import AdapterStatus, AdapterResult, BountyCandidate

        raw_root = str(tmp_path / "raw")
        config = Config(hbhome=str(tmp_path), raw_storage_path=str(tmp_path / "raw"))
        db = Database.create(config)
        ensure_schema(db)

        eng = create_discovery_engine(config=config, db=db)
        assert eng.raw_storage is not None

        # The adapter provides a raw source payload (simulating actual API response).
        source_payload = {
            "api_response_version": "2026-09-15",
            "pagination": {"page": 1, "per_page": 30},
            "items": [
                {
                    "id": "gh-123",
                    "title": "Original API title",
                    "state": "open",
                    "labels": ["bug", "help wanted"],
                }
            ],
            "metadata": {"hostname": "api.github.com", "rate_remaining": 5000},
        }

        c = BountyCandidate(
            source="github",
            source_id="gh-123",
            discovery_run_id="run-001",
            canonical_issue_key="owner/repo#123",
            title="Test Issue",
            description="Test description",
            repository_url="https://github.com/owner/repo",
            issue_url="https://github.com/owner/repo/issues/123",
            reward=None,
            currency=None,
            source_created_at="2026-01-01T00:00:00+00:00",
            source_updated_at="2026-01-01T00:00:00+00:00",
            last_activity="2026-01-01T00:00:00+00:00",
            state="open",
            labels=["bug"],
            raw_payload_reference=None,
            raw_payload_hash=None,
            adapter_version="1.0.0",
            raw_payload=source_payload,  # <-- raw source payload, NOT normalized fields
        )

        class MockAdapter:
            source = "github"
            adapter_version = "1.0.0"

            def fetch(self, run_context):
                return AdapterResult(
                    source="github",
                    adapter_version="1.0.0",
                    status=AdapterStatus.SUCCESS,
                    candidates=[c],
                    pages_fetched=1,
                    candidates_fetched=1,
                    error=None,
                    rate_limit_hit=False,
                    elapsed_seconds=0.1,
                )

        result = eng.run(adapters=[MockAdapter()])
        assert result.candidates_inserted == 1

        row = db.connection.execute(
            "SELECT raw_payload_reference, raw_payload_hash FROM bounties WHERE source = ? AND source_id = ?",
            ("github", "gh-123"),
        ).fetchone()
        assert row is not None
        assert row["raw_payload_reference"] is not None
        assert row["raw_payload_hash"] is not None

        # Verify evidence file content matches the SOURCE payload, not the
        # normalized candidate fields.
        storage = eng.raw_storage
        rel_path = row["raw_payload_reference"]
        assert storage.verify(rel_path, row["raw_payload_hash"]) is True

        full_path = os.path.join(storage.root, rel_path)
        with open(full_path, "rb") as fh:
            stored = json.loads(fh.read())
        assert stored["api_response_version"] == "2026-09-15"
        assert stored["pagination"]["page"] == 1
        assert stored["metadata"]["hostname"] == "api.github.com"
        # Confirm the stored evidence is NOT the normalized candidate fields
        assert "title" not in stored or stored.get("title") != "Test Issue"

        db.close()

    def test_provenance_failure_blocks_persistence(self, tmp_path):
        """GH-2B corrective: when raw_storage is configured but raw_payload
        is missing, the candidate MUST NOT be persisted."""
        from hbh.core.config import Config
        from hbh.core.database import Database, ensure_schema
        from hbh.discovery.engine import create_discovery_engine
        from hbh.discovery.models import AdapterStatus, AdapterResult, BountyCandidate

        config = Config(hbhome=str(tmp_path), raw_storage_path=str(tmp_path / "raw"))
        db = Database.create(config)
        ensure_schema(db)

        eng = create_discovery_engine(config=config, db=db)
        assert eng.raw_storage is not None

        c = BountyCandidate(
            source="github",
            source_id="gh-999",
            discovery_run_id="run-001",
            canonical_issue_key="owner/repo#999",
            title="Should be rejected",
            description="Will not persist due to missing raw_payload",
            repository_url="https://github.com/owner/repo",
            issue_url="https://github.com/owner/repo/issues/999",
            reward=None,
            currency=None,
            source_created_at="2026-01-01T00:00:00+00:00",
            source_updated_at="2026-01-01T00:00:00+00:00",
            last_activity="2026-01-01T00:00:00+00:00",
            state="open",
            labels=[],
            raw_payload_reference=None,
            raw_payload_hash=None,
            adapter_version="1.0.0",
            raw_payload=None,  # MISSING — provenance failure
        )

        class MockAdapter:
            source = "github"
            adapter_version = "1.0.0"

            def fetch(self, run_context):
                return AdapterResult(
                    source="github",
                    adapter_version="1.0.0",
                    status=AdapterStatus.SUCCESS,
                    candidates=[c],
                    pages_fetched=1,
                    candidates_fetched=1,
                    error=None,
                    rate_limit_hit=False,
                    elapsed_seconds=0.1,
                )

        result = eng.run(adapters=[MockAdapter()])
        assert result.candidates_inserted == 0

        # No DB record should exist.
        row = db.connection.execute(
            "SELECT 1 FROM bounties WHERE source = ? AND source_id = ?",
            ("github", "gh-999"),
        ).fetchone()
        assert row is None

        db.close()

    def test_storage_failure_blocks_persistence(self, tmp_path):
        """GH-2B corrective: when raw_storage is configured but a storage
        write fails, the candidate MUST NOT be persisted."""
        from hbh.core.config import Config
        from hbh.core.database import Database, ensure_schema
        from hbh.discovery.engine import create_discovery_engine
        from hbh.discovery.raw_storage import RawStorage
        from hbh.discovery.models import AdapterStatus, AdapterResult, BountyCandidate

        raw_root = str(tmp_path / "raw")
        config = Config(hbhome=str(tmp_path), raw_storage_path=raw_root)
        db = Database.create(config)
        ensure_schema(db)

        # Create a RawStorage that will fail on every write.
        class FailingStorage(RawStorage):
            def store(self, source, payload):
                raise RawStorageError("simulated storage failure")

        failing = FailingStorage(raw_root)

        eng = create_discovery_engine(config=config, db=db)
        eng.raw_storage = failing  # override with failing storage

        c = BountyCandidate(
            source="github",
            source_id="gh-888",
            discovery_run_id="run-001",
            canonical_issue_key="owner/repo#888",
            title="Will be rejected on storage failure",
            description="Storage will fail",
            repository_url="https://github.com/owner/repo",
            issue_url="https://github.com/owner/repo/issues/888",
            reward=None,
            currency=None,
            source_created_at="2026-01-01T00:00:00+00:00",
            source_updated_at="2026-01-01T00:00:00+00:00",
            last_activity="2026-01-01T00:00:00+00:00",
            state="open",
            labels=[],
            raw_payload_reference=None,
            raw_payload_hash=None,
            adapter_version="1.0.0",
            raw_payload={"data": "will not be stored"},
        )

        class MockAdapter:
            source = "github"
            adapter_version = "1.0.0"

            def fetch(self, run_context):
                return AdapterResult(
                    source="github",
                    adapter_version="1.0.0",
                    status=AdapterStatus.SUCCESS,
                    candidates=[c],
                    pages_fetched=1,
                    candidates_fetched=1,
                    error=None,
                    rate_limit_hit=False,
                    elapsed_seconds=0.1,
                )

        result = eng.run(adapters=[MockAdapter()])
        assert result.candidates_inserted == 0

        # No DB record.
        row = db.connection.execute(
            "SELECT 1 FROM bounties WHERE source = ? AND source_id = ?",
            ("github", "gh-888"),
        ).fetchone()
        assert row is None

        db.close()

    def test_engine_without_raw_storage_accepts_null_payload(self, tmp_path):
        """Without raw_storage configured, raw_payload is not required
        and the engine persists candidates with raw_ref=None."""
        from hbh.core.config import Config
        from hbh.core.database import Database, ensure_schema
        from hbh.discovery.engine import create_discovery_engine
        from hbh.discovery.models import AdapterStatus, AdapterResult, BountyCandidate

        config = Config(hbhome=str(tmp_path), raw_storage_path=None)
        db = Database.create(config)
        ensure_schema(db)

        eng = create_discovery_engine(config=config, db=db)
        assert eng.raw_storage is None

        c = BountyCandidate(
            source="github",
            source_id="gh-456",
            discovery_run_id="run-001",
            canonical_issue_key="owner/repo#456",
            title="Test",
            description="Test",
            repository_url="https://github.com/owner/repo",
            issue_url="https://github.com/owner/repo/issues/456",
            reward=None,
            currency=None,
            source_created_at="2026-01-01T00:00:00+00:00",
            source_updated_at="2026-01-01T00:00:00+00:00",
            last_activity="2026-01-01T00:00:00+00:00",
            state="open",
            labels=[],
            raw_payload_reference=None,
            raw_payload_hash=None,
            adapter_version="1.0.0",
            raw_payload=None,  # allowed without raw_storage
        )

        class MockAdapter:
            source = "github"
            adapter_version = "1.0.0"

            def fetch(self, run_context):
                return AdapterResult(
                    source="github",
                    adapter_version="1.0.0",
                    status=AdapterStatus.SUCCESS,
                    candidates=[c],
                    pages_fetched=1,
                    candidates_fetched=1,
                    error=None,
                    rate_limit_hit=False,
                    elapsed_seconds=0.1,
                )

        result = eng.run(adapters=[MockAdapter()])
        assert result.candidates_inserted == 1

        row = db.connection.execute(
            "SELECT raw_payload_reference, raw_payload_hash FROM bounties WHERE source = ? AND source_id = ?",
            ("github", "gh-456"),
        ).fetchone()
        assert row is not None
        assert row["raw_payload_reference"] is None
        assert row["raw_payload_hash"] is None

        db.close()
