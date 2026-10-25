"""
HBH Repository Profiler — GitHub Metadata Adapter (RP-2 Unit A) tests.

Tests use mocked GitHubHTTPClient and RawStorage; no live GitHub API access.
"""

from __future__ import annotations

import inspect
import json
from datetime import datetime, timezone
from unittest import mock as unittest_mock

import pytest

from hbh.discovery.github import metadata_adapter as adapter_mod
from hbh.discovery.github.http_client import GitHubHTTPError
from hbh.discovery.github.metadata_adapter import GitHubMetadataAdapter
from hbh.discovery.profile import (
    ADAPTER_CONTRACT_VERSION,
    ProfileResult,
    ProfileStatus,
    ProfileRunContext,
    RepositoryIdentity,
    make_repository_identity,
)
from hbh.discovery.raw_storage import RawStorageError

# ---------------------------------------------------------------------------
# Shared fixtures and helpers
# ---------------------------------------------------------------------------


def _make_http_client(
    status_code=200,
    body=None,
    *,
    side_effect=None,
):
    client = unittest_mock.MagicMock()
    response = unittest_mock.MagicMock()
    response.status_code = status_code
    response.body = body if body is not None else b""
    client.request.return_value = response
    if side_effect is not None:
        client.request.side_effect = side_effect
    return client


def _make_raw_storage(reference="github/abc123.json", digest="abc123" * 12):
    storage = unittest_mock.MagicMock()
    storage.store.return_value = (reference, digest)
    return storage


def _make_repository_identity(**overrides):
    defaults = dict(
        source="github",
        repository="owner/repo",
        canonical_url="https://github.com/owner/repo",
        owner="owner",
        name="repo",
    )
    defaults.update(overrides)
    return RepositoryIdentity(**defaults)


def _make_run_context(profile_run_id="run-001", repository=None, source_config=None):
    from hbh.discovery.profile import ProfileRunContext

    if repository is None:
        repository = make_repository_identity()
    return ProfileRunContext(
        profile_run_id=profile_run_id,
        started_at=datetime.now(timezone.utc),
        repository=repository,
        source_config=source_config or {},
    )




@pytest.fixture
def http_client():
    return unittest_mock.MagicMock()


@pytest.fixture
def raw_storage():
    storage = unittest_mock.MagicMock()
    storage.store.return_value = ("github/default.json", "0" * 64)
    return storage


@pytest.fixture
def adapter(http_client, raw_storage):
    return GitHubMetadataAdapter(http_client, raw_storage)


@pytest.fixture
def run_context():
    return _make_run_context()


# Shared payloads -------------------------------------------------------

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

MALFORMED_BODY = b"{not valid json"
NON_OBJECT_BODY = json.dumps([1, 2, 3]).encode()


# ---------------------------------------------------------------------------
# Identity validation (RP-1 contract)
# ---------------------------------------------------------------------------


def test_identity_mismatch_raises():
    # An identity whose repository/owner/name do not agree, or a non-https
    # canonical_url, must be rejected at construction (frozen dataclass).
    with pytest.raises(ValueError):
        RepositoryIdentity(
            source="github",
            repository="owner/repo2",
            canonical_url="https://github.com/owner/repo",
            owner="owner",
            name="repo",
        )


def test_identity_is_valid():
    from hbh.discovery.github.metadata_adapter import _identity_is_valid

    assert _identity_is_valid(make_repository_identity()) is True
    assert _identity_is_valid(None) is False
    # Non-RepositoryIdentity objects must not pass the guard.
    assert _identity_is_valid("github:owner/repo") is False
    assert _identity_is_valid(12345) is False


# ---------------------------------------------------------------------------
# Metadata mapping
# ---------------------------------------------------------------------------


def test_full_metadata_mapping(adapter, http_client, raw_storage, run_context):
    http_client.request.return_value.status_code = 200
    http_client.request.return_value.body = json.dumps(FULL_PAYLOAD).encode()
    raw_storage.store.return_value = ("github/abc123.json", "9f86b730f01cfcb1ca17f4b6b6bdf4b3c8b2b8e0f4d1b9d3f961b8e8f2a1b2c3")

    result = adapter.profile(make_repository_identity(), run_context)

    assert result.status == ProfileStatus.SUCCESS
    profile = result.profile
    assert profile.source == "github"
    assert profile.owner == "owner"
    assert profile.name == "repo"
    assert profile.canonical_url == "https://github.com/owner/repo"
    assert profile.visibility == "public"
    assert profile.archived is False
    assert profile.fork is False
    assert profile.default_branch == "main"
    assert profile.description == "A test repository"
    assert profile.created_at == "2021-01-01T00:00:00Z"
    assert profile.updated_at == "2021-06-01T00:00:00Z"
    assert profile.pushed_at == "2021-06-01T00:00:00Z"
    assert profile.size_kb == 1024
    assert profile.primary_language == "Python"
    assert profile.language_breakdown is None  # V1 single endpoint: no breakdown
    assert profile.license_detected is True
    assert profile.license_spdx_id == "MIT"
    assert profile.license_name == "MIT License"
    assert profile.open_issues_count == 3
    assert profile.stars == 42
    assert profile.forks_count == 7
    assert profile.watchers == 13
    assert profile.profile_run_id == "run-001"
    assert profile.source_endpoint == "/repos/owner/repo"
    assert profile.adapter_version == ADAPTER_CONTRACT_VERSION
    assert profile.raw_payload_reference == "github/abc123.json"
    assert profile.raw_payload_hash == "9f86b730f01cfcb1ca17f4b6b6bdf4b3c8b2b8e0f4d1b9d3f961b8e8f2a1b2c3"

    raw_storage.store.assert_called_once_with("github", FULL_PAYLOAD)


def test_optional_metadata_not_available(adapter, http_client, raw_storage, run_context):
    payload = {
        "visibility": None,
        "archived": None,
        "fork": None,
        "default_branch": None,
        "description": None,
        "created_at": None,
        "updated_at": None,
        "pushed_at": None,
        "size": None,
        "language": None,
        "license": None,
        "open_issues_count": None,
        "stargazers_count": None,
        "forks_count": None,
        "watchers_count": None,
    }
    http_client.request.return_value.status_code = 200
    http_client.request.return_value.body = json.dumps(payload).encode()

    result = adapter.profile(make_repository_identity(), run_context)

    assert result.status == ProfileStatus.SUCCESS
    profile = result.profile
    assert profile.visibility is None
    assert profile.archived is None
    assert profile.fork is None
    assert profile.default_branch is None
    assert profile.description is None
    assert profile.created_at is None
    assert profile.updated_at is None
    assert profile.pushed_at is None
    assert profile.size_kb is None
    assert profile.language_breakdown is None
    assert profile.license_detected is False
    assert profile.license_spdx_id is None
    assert profile.license_name is None
    assert profile.open_issues_count is None
    assert profile.stars is None
    assert profile.forks_count is None
    assert profile.watchers is None


# ---------------------------------------------------------------------------
# Malformed payloads
# ---------------------------------------------------------------------------


def test_malformed_json(adapter, http_client, raw_storage, run_context):
    http_client.request.return_value.status_code = 200
    http_client.request.return_value.body = MALFORMED_BODY

    result = adapter.profile(make_repository_identity(), run_context)

    assert result.status == ProfileStatus.FAILED
    assert result.profile is None
    assert "Malformed" in result.error


def test_non_object_payload(adapter, http_client, raw_storage, run_context):
    http_client.request.return_value.status_code = 200
    http_client.request.return_value.body = NON_OBJECT_BODY

    result = adapter.profile(make_repository_identity(), run_context)

    assert result.status == ProfileStatus.FAILED
    assert result.profile is None
    assert "JSON object" in result.error


# ---------------------------------------------------------------------------
# HTTP status handling
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status_code", [401, 403, 404, 429, 500, 503])
def test_http_status_failed(adapter, http_client, raw_storage, run_context, status_code):
    http_client.request.return_value.status_code = status_code

    result = adapter.profile(make_repository_identity(), run_context)

    assert result.status == ProfileStatus.FAILED
    assert result.profile is None
    assert result.error
    if status_code == 429:
        assert result.rate_limit_hit is True
    else:
        assert result.rate_limit_hit is False


def test_timeout_and_network_error(adapter, http_client, raw_storage, run_context):
    # The injected GitHubHTTPClient wraps transport failures into
    # GitHubHTTPError; the adapter must handle those (and only those).
    for exc in (
        GitHubHTTPError("connection timed out"),
        GitHubHTTPError("network unreachable"),
    ):
        http_client.request.reset_mock()
        assert http_client.request.call_count == 0
        http_client.request.side_effect = exc
        result = adapter.profile(make_repository_identity(), run_context)
        assert result.status == ProfileStatus.FAILED
        assert result.profile is None
        assert result.error
        assert http_client.request.call_count == 1


# ---------------------------------------------------------------------------
# Raw evidence
# ---------------------------------------------------------------------------


def test_raw_evidence_ref_and_hash(adapter, http_client, raw_storage, run_context):
    http_client.request.return_value.status_code = 200
    http_client.request.return_value.body = json.dumps(FULL_PAYLOAD).encode()
    raw_storage.store.return_value = ("github/def456.json", "def456" * 12)

    result = adapter.profile(make_repository_identity(), run_context)

    assert result.status == ProfileStatus.SUCCESS
    assert result.profile.raw_payload_reference == "github/def456.json"
    assert result.profile.raw_payload_hash == "def456" * 12
    raw_storage.store.assert_called_once_with("github", FULL_PAYLOAD)


def test_raw_storage_failure_is_fail_closed(adapter, http_client, raw_storage, run_context):
    http_client.request.return_value.status_code = 200
    http_client.request.return_value.body = json.dumps(FULL_PAYLOAD).encode()
    raw_storage.store.side_effect = RawStorageError("disk full")

    result = adapter.profile(make_repository_identity(), run_context)

    assert result.status == ProfileStatus.FAILED
    assert result.profile is None
    assert "storage failed" in result.error
    raw_storage.store.assert_called_once()


# ---------------------------------------------------------------------------
# Adapter version
# ---------------------------------------------------------------------------


def test_adapter_version_constant(adapter, http_client, raw_storage, run_context):
    http_client.request.return_value.status_code = 200
    http_client.request.return_value.body = json.dumps(FULL_PAYLOAD).encode()

    result = adapter.profile(make_repository_identity(), run_context)

    assert result.status == ProfileStatus.SUCCESS
    assert result.profile.adapter_version == ADAPTER_CONTRACT_VERSION


# ---------------------------------------------------------------------------
# No retry / no sleep / no execution side effects
# ---------------------------------------------------------------------------


def test_no_retry_or_sleep(adapter, http_client, raw_storage, run_context):
    http_client.request.return_value.status_code = 429

    result = adapter.profile(make_repository_identity(), run_context)

    assert result.status == ProfileStatus.FAILED
    assert result.rate_limit_hit is True
    # Single attempt only: no retry loop, no backoff, no sleep.
    assert http_client.request.call_count == 1

    import inspect

    module_source = inspect.getsource(adapter_mod)
    assert "time.sleep(" not in module_source
    assert "sleep(" not in module_source


def test_no_subprocess_sqlite_state_transition(adapter, http_client, raw_storage, run_context):
    import hbh.discovery.github.metadata_adapter as adapter_module
    import hbh.discovery.github.http_client as http_module

    # No remote / execution / persistence primitives in the adapter.
    assert "subprocess" not in dir(adapter_module)
    assert "sqlite3" not in dir(adapter_module)
    assert "state_machine" not in dir(adapter_module)
    assert "subprocess" not in dir(http_module)
    assert not hasattr(adapter_module, "git")
    assert not hasattr(adapter_module, "_update_state")
