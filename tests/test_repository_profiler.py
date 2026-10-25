"""
Tests for hbh.discovery.profiler (RepositoryProfiler, RP-2 Unit C).

All tests are isolated: real HTTP/network and real SQLite are never used.
GitHubMetadataAdapter / RawStorage are injected (or mocked) so every case
is deterministic and reproducible without external services.

Cakupan minimum:
  1. Success returns ProfileResult + RepositoryProfile faithfully.
  2. ProfileRunContext given to the adapter originates from Unit B and
     carries the correct repository identity + profile_run_id.
  3. source_config / started_at follow the Unit B contract.
  4. FAILED results from the adapter are passed through unmasked.
  5. 404 / 401 / 429 / malformed JSON fail through a mocked adapter.
  6. Raw-storage failure stays fail-closed per Unit A.
  7. Raw-reference/hash forwarded exactly when the adapter provides them.
  8. No retry / repeated adapter invocation.
  9. No SQLite/state/audit/subprocess/network used by the profiler module.
  10. Input validation follows the actual Unit B + RP-1 contracts.
  11. Dependency injection tested without creating unnecessary clients.
"""

import inspect
import json
from datetime import datetime, timezone
from typing import Any, Optional
from unittest import mock as unittest_mock

import pytest

from hbh.discovery.github.metadata_adapter import GitHubMetadataAdapter
from hbh.discovery.github.http_client import GitHubHTTPError
from hbh.discovery.profile import (
    ProfileRunContext,
    RepositoryIdentity,
    ProfileResult,
    ProfileStatus,
    build_profile_run_context,
    make_repository_profile,
)
from hbh.discovery.raw_storage import RawStorageError
from hbh.discovery.profiler import RepositoryProfiler

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_identity(**overrides) -> RepositoryIdentity:
    defaults = dict(
        source="github",
        repository="owner/repo",
        canonical_url="https://github.com/owner/repo",
        owner="owner",
        name="repo",
    )
    defaults.update(overrides)
    return RepositoryIdentity(**defaults)


def _make_adapter(http_client=None, raw_storage=None) -> GitHubMetadataAdapter:
    if http_client is None:
        http_client = unittest_mock.MagicMock()
    if raw_storage is None:
        raw_storage = unittest_mock.MagicMock()
    return GitHubMetadataAdapter(http_client=http_client, raw_storage=raw_storage)


FULL_PAYLOAD = {
    "visibility": "public",
    "archived": False,
    "fork": False,
    "default_branch": "main",
    "description": "A test repository",
    "created_at": "2021-01-01T00:00:00Z",
    "updated_at": "2021-06-01T00:00:00Z",
    "pushed_at": "2021-06-01T00:00:00Z",
    "size": 1024,
    "language": "Python",
    "license": {"spdx_id": "MIT", "name": "MIT License"},
    "open_issues_count": 3,
    "stargazers_count": 42,
    "forks_count": 7,
    "watchers_count": 13,
}


def _response(status_code=200, body=None):
    response = unittest_mock.MagicMock()
    response.status_code = status_code
    response.body = body if body is not None else json.dumps(FULL_PAYLOAD).encode()
    return response


# ---------------------------------------------------------------------------
# Dependency injection
# ---------------------------------------------------------------------------

class TestDependencyInjection:
    def test_accepts_adapter_directly(self):
        adapter = _make_adapter()
        profiler = RepositoryProfiler(adapter)
        assert profiler._adapter is adapter

    def test_single_adapter_no_duplicate_client_or_storage(self):
        http_client = unittest_mock.MagicMock()
        raw_storage = unittest_mock.MagicMock()
        adapter = GitHubMetadataAdapter(
            http_client=http_client, raw_storage=raw_storage
        )
        profiler = RepositoryProfiler(adapter)
        # Only one adapter; the profiler holds it, sharing the same client /
        # storage the caller provided.
        assert profiler._adapter is adapter
        assert profiler._adapter._http_client is http_client
        assert profiler._adapter._raw_storage is raw_storage

    def test_injected_adapter_avoid_client_storage_creation(self):
        # Injecting the adapter directly means no GitHubHTTPClient / RawStorage
        # has to be constructed just to run the profiler.
        fake_adapter = unittest_mock.MagicMock()
        profiler = RepositoryProfiler(fake_adapter)
        profiler.profile(_make_identity(), "run-001")
        assert fake_adapter.profile.called


# ---------------------------------------------------------------------------
# Successful profile through the real adapter
# ---------------------------------------------------------------------------

class TestSuccessfulProfile:
    def test_success_returns_result_with_provenance(self):
        http_client = unittest_mock.MagicMock()
        raw_storage = unittest_mock.MagicMock()
        raw_storage.store.return_value = ("github/abc123.json", "abc123" * 12)
        adapter = _make_adapter(http_client=http_client, raw_storage=raw_storage)
        profiler = RepositoryProfiler(adapter)
        http_client.request.return_value = _response(
            status_code=200,
            body=json.dumps(FULL_PAYLOAD).encode(),
        )

        result = profiler.profile(_make_identity(), "run-001")

        assert result.status == ProfileStatus.SUCCESS
        assert result.profile is not None
        profile = result.profile
        assert profile.profile_run_id == "run-001"
        assert profile.raw_payload_reference == "github/abc123.json"
        assert profile.raw_payload_hash == "abc123" * 12
        assert profile.source_endpoint == "/repos/owner/repo"
        raw_storage.store.assert_called_once_with("github", FULL_PAYLOAD)
        http_client.request.assert_called_once_with(
            "/repos/owner/repo", params=None
        )

    def test_no_retry_no_reentry(self):
        # Rate-limit response should stop after a single HTTP attempt.
        http_client = unittest_mock.MagicMock()
        http_client.request.return_value.status_code = 429
        adapter = _make_adapter(http_client=http_client)
        profiler = RepositoryProfiler(adapter)

        result = profiler.profile(_make_identity(), "run-001")

        assert result.status == ProfileStatus.FAILED
        assert result.profile is None
        assert result.rate_limit_hit is True
        assert http_client.request.call_count == 1


# ---------------------------------------------------------------------------
# Unit B context delegation
# ---------------------------------------------------------------------------

class TestUnitBContext:
    def test_run_context_uses_unit_b_factory(self):
        fake_adapter = unittest_mock.MagicMock()
        profiler = RepositoryProfiler(fake_adapter)
        repo = _make_identity()
        given = datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone.utc)
        config = {"github": {"enabled": True}}

        profiler.profile(repo, "run-001", started_at=given, source_config=config)

        fake_adapter.profile.assert_called_once()
        called_ctx = fake_adapter.profile.call_args.kwargs["run_context"]
        assert called_ctx.profile_run_id == "run-001"
        assert called_ctx.repository is repo
        assert called_ctx.started_at == given
        assert called_ctx.source_config is config

    def test_source_config_none_becomes_empty_dict(self):
        fake_adapter = unittest_mock.MagicMock()
        profiler = RepositoryProfiler(fake_adapter)
        profiler.profile(_make_identity(), "run-001", source_config=None)
        called_ctx = fake_adapter.profile.call_args.kwargs["run_context"]
        assert called_ctx.source_config == {}

    def test_started_at_none_gives_utc_timestamp(self):
        fake_adapter = unittest_mock.MagicMock()
        profiler = RepositoryProfiler(fake_adapter)
        before = datetime.now(timezone.utc)
        profiler.profile(_make_identity(), "run-001")
        after = datetime.now(timezone.utc)
        called_ctx = fake_adapter.profile.call_args.kwargs["run_context"]
        assert before <= called_ctx.started_at <= after
        assert called_ctx.started_at.tzinfo is not None
        assert called_ctx.started_at.utcoffset().total_seconds() == 0

    def test_started_at_preserved_as_given(self):
        fake_adapter = unittest_mock.MagicMock()
        profiler = RepositoryProfiler(fake_adapter)
        given = datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone.utc)
        profiler.profile(_make_identity(), "run-001", started_at=given)
        called_ctx = fake_adapter.profile.call_args.kwargs["run_context"]
        assert called_ctx.started_at is given


# ---------------------------------------------------------------------------
# Failed profiles - real adapter, no masking
# ---------------------------------------------------------------------------

class TestFailedProfiles:
    @pytest.mark.parametrize(
        "status_code,rate_limit_expected",
        [
            (404, False),
            (401, False),
            (429, True),
        ],
    )
    def test_status_failed_passed_through(self, status_code, rate_limit_expected):
        http_client = unittest_mock.MagicMock()
        http_client.request.return_value.status_code = status_code
        adapter = _make_adapter(http_client=http_client)
        profiler = RepositoryProfiler(adapter)

        result = profiler.profile(_make_identity(), "run-001")

        assert result.status == ProfileStatus.FAILED
        assert result.profile is None
        assert result.rate_limit_hit == rate_limit_expected
        # No retry: exactly one transport request.
        assert http_client.request.call_count == 1

    def test_malformed_json_failed(self):
        http_client = unittest_mock.MagicMock()
        http_client.request.return_value.status_code = 200
        http_client.request.return_value.body = b"{not valid json"
        adapter = _make_adapter(http_client=http_client)
        profiler = RepositoryProfiler(adapter)

        result = profiler.profile(_make_identity(), "run-001")

        assert result.status == ProfileStatus.FAILED
        assert result.profile is None
        assert "Malformed" in result.error
        assert http_client.request.call_count == 1

    def test_failed_result_passed_through_unmodified(self):
        expected = ProfileResult(
            status=ProfileStatus.FAILED,
            profile=None,
            error="repository not found (404)",
            rate_limit_hit=False,
            elapsed_seconds=0.42,
        )
        fake_adapter = unittest_mock.MagicMock()
        fake_adapter.profile.return_value = expected
        profiler = RepositoryProfiler(fake_adapter)

        result = profiler.profile(_make_identity(), "run-001")

        # Returned as the same object - nothing copied or reconstituted.
        assert result is expected
        fake_adapter.profile.assert_called_once()

    def test_partial_result_passed_through_unmodified(self):
        partial = ProfileResult(
            status=ProfileStatus.PARTIAL,
            profile=make_repository_profile(),
            rate_limit_hit=True,
            elapsed_seconds=0.5,
        )
        fake_adapter = unittest_mock.MagicMock()
        fake_adapter.profile.return_value = partial
        profiler = RepositoryProfiler(fake_adapter)

        result = profiler.profile(_make_identity(), "run-001")

        assert result is partial
        assert result.status == ProfileStatus.PARTIAL


# ---------------------------------------------------------------------------
# Raw evidence store fail-closed
# ---------------------------------------------------------------------------

class TestRawStorageFailClosed:
    def test_storage_failure_passed_through_as_failure(self):
        http_client = unittest_mock.MagicMock()
        raw_storage = unittest_mock.MagicMock()
        raw_storage.store.side_effect = RawStorageError("disk full")
        adapter = _make_adapter(http_client=http_client, raw_storage=raw_storage)
        http_client.request.return_value.status_code = 200
        http_client.request.return_value.body = json.dumps(FULL_PAYLOAD).encode()
        profiler = RepositoryProfiler(adapter)

        result = profiler.profile(_make_identity(), "run-001", source_config=None)

        assert result.status == ProfileStatus.FAILED
        assert result.profile is None
        assert "storage failed" in result.error
        raw_storage.store.assert_called_once_with("github", FULL_PAYLOAD)
        http_client.request.assert_called_once()


# ---------------------------------------------------------------------------
# Forbidden side effects (module-level inspection)
# ---------------------------------------------------------------------------

class TestNoForbiddenSideEffects:
    def test_no_sqlite_state_audit_or_subprocess_in_source(self):
        import hbh.discovery.profiler as profiler_mod

        source = inspect.getsource(profiler_mod)
        for forbidden in ("sqlite3", "state_machine", "AuditLogger", "subprocess"):
            assert forbidden not in source, (
                f"profiler module must not reference {forbidden}"
            )

    def test_no_network_primitives_in_source(self):
        import hbh.discovery.profiler as profiler_mod

        source = inspect.getsource(profiler_mod)
        for forbidden in ("urllib", "http.client", "requests", "socket"):
            assert forbidden not in source, (
                f"profiler module must not use {forbidden}"
            )


# ---------------------------------------------------------------------------
# Input validation (actual Unit B + RP-1 contracts)
# ---------------------------------------------------------------------------

class TestInputValidation:
    def test_empty_profile_run_id_rejected(self):
        adapter = _make_adapter()
        profiler = RepositoryProfiler(adapter)
        with pytest.raises(ValueError, match="profile_run_id must be a non-empty string"):
            profiler.profile(_make_identity(), "")

    def test_whitespace_profile_run_id_rejected(self):
        adapter = _make_adapter()
        profiler = RepositoryProfiler(adapter)
        with pytest.raises(ValueError, match="profile_run_id must be a non-empty string"):
            profiler.profile(_make_identity(), "   ")

    def test_none_profile_run_id_rejected(self):
        adapter = _make_adapter()
        profiler = RepositoryProfiler(adapter)
        with pytest.raises(ValueError, match="profile_run_id must be a non-empty string"):
            profiler.profile(_make_identity(), None)

    def test_non_string_profile_run_id_rejected(self):
        adapter = _make_adapter()
        profiler = RepositoryProfiler(adapter)
        with pytest.raises(ValueError, match="profile_run_id must be a non-empty string"):
            profiler.profile(_make_identity(), 12345)

    def test_repository_not_identity_rejected(self):
        adapter = _make_adapter()
        profiler = RepositoryProfiler(adapter)
        with pytest.raises(ValueError, match="repository must be an instance of RepositoryIdentity"):
            profiler.profile("github:owner/repo", "run-001")


# ---------------------------------------------------------------------------
# End of tests
# ---------------------------------------------------------------------------
