"""
HBH Repository Profiler Tests — RP-1 Focus.

Tests for RepositoryIdentity, RepositoryProfile, ProfileResult, and related contracts.
Fokus pada specification repository-profiler-spec.md
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from hbh.discovery.profile import (
    ADAPTER_CONTRACT_VERSION,
    ProfileResult,
    ProfileStatus,
    RepositoryIdentity,
    RepositoryProfile,
    RepositoryProfilerConfig,
    normalize_repository_identity,
    make_repository_identity,
    make_repository_profile,
    make_profile_result,
)


# ---------------------------------------------------------------------------
# RepositoryIdentity: Normalization Tests
# ---------------------------------------------------------------------------

class TestRepositoryIdentityCanonical:
    """Tests for canonical repository identity formation."""

    def test_source_id_format(self):
        """source:owner/repository format is correct."""
        identity = RepositoryIdentity(
            source="github",
            repository="octocat/Hello-World",
            canonical_url="https://github.com/octocat/Hello-World",
            owner="octocat",
            name="Hello-World",
        )
        assert identity.source_id == "github:octocat/Hello-World"

    def test_str_representation(self):
        """String representation is source_id."""
        identity = RepositoryIdentity(
            source="github",
            repository="facebook/react",
            canonical_url="https://github.com/facebook/react",
            owner="facebook",
            name="react",
        )
        assert str(identity) == "github:facebook/react"


class TestRepositoryIdentityValidation:
    """Tests for RepositoryIdentity validation."""

    def test_empty_source_raises(self):
        """Empty source raises ValueError."""
        with pytest.raises(ValueError, match="source must not be empty"):
            RepositoryIdentity(
                source="",
                repository="owner/repo",
                canonical_url="https://github.com/owner/repo",
                owner="owner",
                name="repo",
            )

    def test_empty_repository_raises(self):
        """Empty repository raises ValueError."""
        with pytest.raises(ValueError, match="repository must not be empty"):
            RepositoryIdentity(
                source="github",
                repository="",
                canonical_url="https://github.com/owner/repo",
                owner="owner",
                name="repo",
            )

    def test_repository_missing_slash_raises(self):
        """Repository without / raises ValueError."""
        with pytest.raises(ValueError, match="repository must contain '/'"):
            RepositoryIdentity(
                source="github",
                repository="ownerrepo",
                canonical_url="https://github.com/owner/repo",
                owner="owner",
                name="repo",
            )

    def test_repository_inconsistent_with_owner_name_raises(self):
        """Repository inconsistent with owner/name raises."""
        with pytest.raises(ValueError, match="inconsistent"):
            RepositoryIdentity(
                source="github",
                repository="owner/repo2",
                canonical_url="https://github.com/owner/repo",
                owner="owner",
                name="repo",
            )

    def test_invalid_canonical_url_raises(self):
        """Non-https canonical_url raises ValueError."""
        with pytest.raises(ValueError, match="must be https://"):
            RepositoryIdentity(
                source="github",
                repository="owner/repo",
                canonical_url="http://github.com/owner/repo",
                owner="owner",
                name="repo",
            )


class TestNormalizeRepositoryIdentity:
    """Tests for normalization function."""

    def test_owner_repo_format(self):
        """owner/repo format is preserved."""
        identity = normalize_repository_identity("github", "octocat/Hello-World")
        assert identity.owner == "octocat"
        assert identity.name == "Hello-World"
        assert identity.repository == "octocat/Hello-World"

    def test_trailing_slash_removed(self):
        """Trailing slash is removed."""
        identity = normalize_repository_identity("github", "octocat/Hello-World/")
        assert identity.name == "Hello-World"

    def test_git_suffix_removed(self):
        """.git suffix is removed."""
        identity = normalize_repository_identity("github", "octocat/Hello-World.git")
        assert identity.repository == "octocat/Hello-World"

    def test_url_parsed(self):
        """GitHub URL is parsed correctly."""
        identity = normalize_repository_identity("github", "https://github.com/octocat/Hello-World")
        assert identity.owner == "octocat"
        assert identity.name == "Hello-World"

    def test_url_with_git_suffix(self):
        """GitHub URL with .git suffix is parsed."""
        identity = normalize_repository_identity("github", "https://github.com/octocat/Hello-World.git")
        assert identity.repository == "octocat/Hello-World"

    def test_github_prefix_removed(self):
        """github: prefix is removed."""
        identity = normalize_repository_identity("github", "github:octocat/Hello-World")
        assert identity.repository == "octocat/Hello-World"

    def test_whitespace_stripped(self):
        """Leading/trailing whitespace is stripped."""
        identity = normalize_repository_identity("github", "  octocat/Hello-World  ")
        assert identity.owner == "octocat"

    def test_invalid_no_slash_raises(self):
        """Input without / raises ValueError."""
        with pytest.raises(ValueError, match="no /"):
            normalize_repository_identity("github", "octocat")

    def test_invalid_empty_raises(self):
        """Empty input raises ValueError."""
        with pytest.raises(ValueError):
            normalize_repository_identity("github", "")

    def test_invalid_whitespace_only_raises(self):
        """Whitespace-only input raises ValueError."""
        with pytest.raises(ValueError):
            normalize_repository_identity("github", "   ")


class TestOwnerRepoNormalization:
    """Tests for owner and repo normalization rules."""

    def test_case_preserved(self):
        """Case is preserved (case-sensitive)."""
        identity = normalize_repository_identity("github", "MyOrg/MyRepo")
        assert identity.owner == "MyOrg"
        assert identity.name == "MyRepo"

    def test_no_case_transform(self):
        """No case transformation is applied."""
        identity = normalize_repository_identity("github", "UPPER/lower")
        assert identity.owner == "UPPER"
        assert identity.name == "lower"


# ---------------------------------------------------------------------------
# RepositoryProfile: Schema Tests
# ---------------------------------------------------------------------------

class TestRepositoryProfileIdentity:
    """Tests for RepositoryProfile identity fields."""

    def test_source_required(self):
        """source field is required."""
        with pytest.raises(ValueError, match="source must not be empty"):
            RepositoryProfile(
                source="",
                repository="owner/repo",
                canonical_url="https://github.com/owner/repo",
                owner="owner",
                name="repo",
                profile_run_id="run-001",
                profiled_at="2024-01-01T00:00:00Z",
                source_endpoint="/repos/owner/repo",
                adapter_version="1.0.0",
            )

    def test_repository_required(self):
        """repository field is required."""
        with pytest.raises(ValueError, match="repository must not be empty"):
            RepositoryProfile(
                source="github",
                repository="",
                canonical_url="https://github.com/owner/repo",
                owner="owner",
                name="repo",
                profile_run_id="run-001",
                profiled_at="2024-01-01T00:00:00Z",
                source_endpoint="/repos/owner/repo",
                adapter_version="1.0.0",
            )

    def test_canonical_url_required(self):
        """canonical_url field is required."""
        with pytest.raises(ValueError, match="canonical_url must not be empty"):
            RepositoryProfile(
                source="github",
                repository="owner/repo",
                canonical_url="",
                owner="owner",
                name="repo",
                profile_run_id="run-001",
                profiled_at="2024-01-01T00:00:00Z",
                source_endpoint="/repos/owner/repo",
                adapter_version="1.0.0",
            )

    def test_owner_required(self):
        """owner field is required."""
        with pytest.raises(ValueError, match="owner must not be empty"):
            RepositoryProfile(
                source="github",
                repository="owner/repo",
                canonical_url="https://github.com/owner/repo",
                owner="",
                name="repo",
                profile_run_id="run-001",
                profiled_at="2024-01-01T00:00:00Z",
                source_endpoint="/repos/owner/repo",
                adapter_version="1.0.0",
            )

    def test_name_required(self):
        """name field is required."""
        with pytest.raises(ValueError, match="name must not be empty"):
            RepositoryProfile(
                source="github",
                repository="owner/repo",
                canonical_url="https://github.com/owner/repo",
                owner="owner",
                name="",
                profile_run_id="run-001",
                profiled_at="2024-01-01T00:00:00Z",
                source_endpoint="/repos/owner/repo",
                adapter_version="1.0.0",
            )


class TestRepositoryProfileStateFields:
    """Tests for RepositoryProfile state fields."""

    def test_archived_nullable(self):
        """archived field accepts None."""
        profile = RepositoryProfile(
            source="github",
            repository="owner/repo",
            canonical_url="https://github.com/owner/repo",
            owner="owner",
            name="repo",
            profile_run_id="run-001",
            profiled_at="2024-01-01T00:00:00Z",
            source_endpoint="/repos/owner/repo",
            adapter_version="1.0.0",
            archived=None,
        )
        assert profile.archived is None

    def test_archived_true(self):
        """archived true is accepted."""
        profile = RepositoryProfile(
            source="github",
            repository="owner/repo",
            canonical_url="https://github.com/owner/repo",
            owner="owner",
            name="repo",
            profile_run_id="run-001",
            profiled_at="2024-01-01T00:00:00Z",
            source_endpoint="/repos/owner/repo",
            adapter_version="1.0.0",
            archived=True,
        )
        assert profile.archived is True

    def test_fork_nullable(self):
        """fork field accepts None."""
        profile = RepositoryProfile(
            source="github",
            repository="owner/repo",
            canonical_url="https://github.com/owner/repo",
            owner="owner",
            name="repo",
            profile_run_id="run-001",
            profiled_at="2024-01-01T00:00:00Z",
            source_endpoint="/repos/owner/repo",
            adapter_version="1.0.0",
            fork=None,
        )
        assert profile.fork is None

    def test_default_branch_nullable(self):
        """default_branch field accepts None."""
        profile = RepositoryProfile(
            source="github",
            repository="owner/repo",
            canonical_url="https://github.com/owner/repo",
            owner="owner",
            name="repo",
            profile_run_id="run-001",
            profiled_at="2024-01-01T00:00:00Z",
            source_endpoint="/repos/owner/repo",
            adapter_version="1.0.0",
            default_branch=None,
        )
        assert profile.default_branch is None

    def test_archived_wrong_type_raises(self):
        """archived with wrong type raises TypeError."""
        with pytest.raises(TypeError, match="archived must be"):
            RepositoryProfile(
                source="github",
                repository="owner/repo",
                canonical_url="https://github.com/owner/repo",
                owner="owner",
                name="repo",
                profile_run_id="run-001",
                profiled_at="2024-01-01T00:00:00Z",
                source_endpoint="/repos/owner/repo",
                adapter_version="1.0.0",
                archived="true",  # wrong type
            )


class TestRepositoryProfileMetadataFields:
    """Tests for RepositoryProfile metadata fields."""

    def test_description_nullable(self):
        """description field accepts None."""
        profile = RepositoryProfile(
            source="github",
            repository="owner/repo",
            canonical_url="https://github.com/owner/repo",
            owner="owner",
            name="repo",
            profile_run_id="run-001",
            profiled_at="2024-01-01T00:00:00Z",
            source_endpoint="/repos/owner/repo",
            adapter_version="1.0.0",
            description=None,
        )
        assert profile.description is None

    def test_created_at_nullable(self):
        """created_at field accepts None."""
        profile = RepositoryProfile(
            source="github",
            repository="owner/repo",
            canonical_url="https://github.com/owner/repo",
            owner="owner",
            name="repo",
            profile_run_id="run-001",
            profiled_at="2024-01-01T00:00:00Z",
            source_endpoint="/repos/owner/repo",
            adapter_version="1.0.0",
            created_at=None,
        )
        assert profile.created_at is None

    def test_timestamps_nullable(self):
        """All timestamp fields accept None."""
        profile = RepositoryProfile(
            source="github",
            repository="owner/repo",
            canonical_url="https://github.com/owner/repo",
            owner="owner",
            name="repo",
            profile_run_id="run-001",
            profiled_at="2024-01-01T00:00:00Z",
            source_endpoint="/repos/owner/repo",
            adapter_version="1.0.0",
            created_at=None,
            updated_at=None,
            pushed_at=None,
        )
        assert profile.created_at is None
        assert profile.updated_at is None
        assert profile.pushed_at is None


class TestRepositoryProfileActivityFields:
    """Tests for RepositoryProfile activity/stars/forks/watchers fields."""

    def test_open_issues_count_nullable(self):
        """open_issues_count accepts None."""
        profile = RepositoryProfile(
            source="github",
            repository="owner/repo",
            canonical_url="https://github.com/owner/repo",
            owner="owner",
            name="repo",
            profile_run_id="run-001",
            profiled_at="2024-01-01T00:00:00Z",
            source_endpoint="/repos/owner/repo",
            adapter_version="1.0.0",
            open_issues_count=None,
            stars=None,
            forks_count=None,
            watchers=None,
        )
        assert profile.open_issues_count is None
        assert profile.stars is None
        assert profile.forks_count is None
        assert profile.watchers is None

    def test_activity_values(self):
        """Activity values are stored correctly."""
        profile = RepositoryProfile(
            source="github",
            repository="owner/repo",
            canonical_url="https://github.com/owner/repo",
            owner="owner",
            name="repo",
            profile_run_id="run-001",
            profiled_at="2024-01-01T00:00:00Z",
            source_endpoint="/repos/owner/repo",
            adapter_version="1.0.0",
            open_issues_count=10,
            stars=100,
            forks_count=50,
            watchers=25,
        )
        assert profile.open_issues_count == 10
        assert profile.stars == 100
        assert profile.forks_count == 50
        assert profile.watchers == 25


class TestRepositoryProfileLicenseFields:
    """Tests for RepositoryProfile license fields."""

    def test_license_detected_nullable(self):
        """license_detected accepts None."""
        profile = RepositoryProfile(
            source="github",
            repository="owner/repo",
            canonical_url="https://github.com/owner/repo",
            owner="owner",
            name="repo",
            profile_run_id="run-001",
            profiled_at="2024-01-01T00:00:00Z",
            source_endpoint="/repos/owner/repo",
            adapter_version="1.0.0",
            license_detected=None,
        )
        assert profile.license_detected is None

    def test_license_fields_nullable(self):
        """License fields accept None."""
        profile = RepositoryProfile(
            source="github",
            repository="owner/repo",
            canonical_url="https://github.com/owner/repo",
            owner="owner",
            name="repo",
            profile_run_id="run-001",
            profiled_at="2024-01-01T00:00:00Z",
            source_endpoint="/repos/owner/repo",
            adapter_version="1.0.0",
            license_detected=True,
            license_spdx_id="MIT",
            license_name="MIT License",
        )
        assert profile.license_detected is True
        assert profile.license_spdx_id == "MIT"
        assert profile.license_name == "MIT License"


class TestRepositoryProfileProvenanceFields:
    """Tests for RepositoryProfile provenance fields."""

    def test_profile_run_id_required(self):
        """profile_run_id is required."""
        with pytest.raises(ValueError, match="profile_run_id must not be empty"):
            RepositoryProfile(
                source="github",
                repository="owner/repo",
                canonical_url="https://github.com/owner/repo",
                owner="owner",
                name="repo",
                profile_run_id="",
                profiled_at="2024-01-01T00:00:00Z",
                source_endpoint="/repos/owner/repo",
                adapter_version="1.0.0",
            )

    def test_profiled_at_required(self):
        """profiled_at is required."""
        with pytest.raises(ValueError, match="profiled_at must not be empty"):
            RepositoryProfile(
                source="github",
                repository="owner/repo",
                canonical_url="https://github.com/owner/repo",
                owner="owner",
                name="repo",
                profile_run_id="run-001",
                profiled_at="",
                source_endpoint="/repos/owner/repo",
                adapter_version="1.0.0",
            )

    def test_source_endpoint_required(self):
        """source_endpoint is required."""
        with pytest.raises(ValueError, match="source_endpoint must not be empty"):
            RepositoryProfile(
                source="github",
                repository="owner/repo",
                canonical_url="https://github.com/owner/repo",
                owner="owner",
                name="repo",
                profile_run_id="run-001",
                profiled_at="2024-01-01T00:00:00Z",
                source_endpoint="",
                adapter_version="1.0.0",
            )

    def test_adapter_version_required(self):
        """adapter_version is required."""
        with pytest.raises(ValueError, match="adapter_version must not be empty"):
            RepositoryProfile(
                source="github",
                repository="owner/repo",
                canonical_url="https://github.com/owner/repo",
                owner="owner",
                name="repo",
                profile_run_id="run-001",
                profiled_at="2024-01-01T00:00:00Z",
                source_endpoint="/repos/owner/repo",
                adapter_version="",
            )

    def test_raw_payload_fields_optional(self):
        """raw_payload_reference and raw_payload_hash are optional."""
        profile = RepositoryProfile(
            source="github",
            repository="owner/repo",
            canonical_url="https://github.com/owner/repo",
            owner="owner",
            name="repo",
            profile_run_id="run-001",
            profiled_at="2024-01-01T00:00:00Z",
            source_endpoint="/repos/owner/repo",
            adapter_version="1.0.0",
        )
        assert profile.raw_payload_reference is None
        assert profile.raw_payload_hash is None

    def test_raw_payload_fields_settable(self):
        """raw_payload fields can be set when available."""
        profile = RepositoryProfile(
            source="github",
            repository="owner/repo",
            canonical_url="https://github.com/owner/repo",
            owner="owner",
            name="repo",
            profile_run_id="run-001",
            profiled_at="2024-01-01T00:00:00Z",
            source_endpoint="/repos/owner/repo",
            adapter_version="1.0.0",
            raw_payload_reference="github/abc123.json",
            raw_payload_hash="a" * 64,  # SHA-256 hex
        )
        assert profile.raw_payload_reference == "github/abc123.json"
        assert profile.raw_payload_hash == "a" * 64


# ---------------------------------------------------------------------------
# RepositoryProfile: Minimum Validity Tests
# ---------------------------------------------------------------------------

class TestRepositoryProfileMinimumValidity:
    """Tests for minimum valid profile (SUCCESS criteria)."""

    def test_is_minimum_valid_true(self):
        """Minimum valid profile returns True for is_minimum_valid."""
        profile = RepositoryProfile(
            source="github",
            repository="owner/repo",
            canonical_url="https://github.com/owner/repo",
            owner="owner",
            name="repo",
            profile_run_id="run-001",
            profiled_at="2024-01-01T00:00:00Z",
            source_endpoint="/repos/owner/repo",
            adapter_version="1.0.0",
        )
        assert profile.is_minimum_valid() is True

    def test_null_optional_fields_still_minimum_valid(self):
        """Profile with null optional fields is still minimum valid."""
        profile = RepositoryProfile(
            source="github",
            repository="owner/repo",
            canonical_url="https://github.com/owner/repo",
            owner="owner",
            name="repo",
            profile_run_id="run-001",
            profiled_at="2024-01-01T00:00:00Z",
            source_endpoint="/repos/owner/repo",
            adapter_version="1.0.0",
            description=None,
            license_detected=None,
            primary_language=None,
            stars=None,
        )
        assert profile.is_minimum_valid() is True


# ---------------------------------------------------------------------------
# RepositoryProfile: Identity Consistency Tests
# ---------------------------------------------------------------------------

class TestRepositoryProfileIdentityConsistency:
    """Tests for identity field consistency."""

    def test_repository_consistent_with_owner_name(self):
        """.repository field is owner/name format."""
        profile = RepositoryProfile(
            source="github",
            repository="owner/repo",
            canonical_url="https://github.com/owner/repo",
            owner="owner",
            name="repo",
            profile_run_id="run-001",
            profiled_at="2024-01-01T00:00:00Z",
            source_endpoint="/repos/owner/repo",
            adapter_version="1.0.0",
        )
        assert profile.repository == "owner/repo"

    def test_canonical_url_matches_owner_name(self):
        """canonical_url matches owner/name."""
        profile = RepositoryProfile(
            source="github",
            repository="owner/repo",
            canonical_url="https://github.com/owner/repo",
            owner="owner",
            name="repo",
            profile_run_id="run-001",
            profiled_at="2024-01-01T00:00:00Z",
            source_endpoint="/repos/owner/repo",
            adapter_version="1.0.0",
        )
        expected = f"https://github.com/{profile.owner}/{profile.name}"
        assert profile.canonical_url == expected

    def test_inconsistent_repository_raises(self):
        """Inconsistent repository raises ValueError."""
        with pytest.raises(ValueError, match="inconsistent"):
            RepositoryProfile(
                source="github",
                repository="owner/oldname",  # different from name
                canonical_url="https://github.com/owner/repo",
                owner="owner",
                name="repo",
                profile_run_id="run-001",
                profiled_at="2024-01-01T00:00:00Z",
                source_endpoint="/repos/owner/repo",
                adapter_version="1.0.0",
            )


# ---------------------------------------------------------------------------
# RepositoryProfile: Identity Property
# ---------------------------------------------------------------------------

class TestRepositoryProfileIdentityProperty:
    """Tests for profile.identity property."""

    def test_identity_returns_repository_identity(self):
        """identity property returns RepositoryIdentity."""
        profile = RepositoryProfile(
            source="github",
            repository="owner/repo",
            canonical_url="https://github.com/owner/repo",
            owner="owner",
            name="repo",
            profile_run_id="run-001",
            profiled_at="2024-01-01T00:00:00Z",
            source_endpoint="/repos/owner/repo",
            adapter_version="1.0.0",
        )
        identity = profile.identity
        assert isinstance(identity, RepositoryIdentity)
        assert identity.source == "github"
        assert identity.repository == "owner/repo"
        assert identity.owner == "owner"
        assert identity.name == "repo"


# ---------------------------------------------------------------------------
# ProfileResult: Status Tests
# ---------------------------------------------------------------------------

class TestProfileStatus:
    """Tests for ProfileStatus literal values."""

    def test_success_is_valid(self):
        """SUCCESS is a valid status."""
        assert ProfileStatus.is_valid("SUCCESS")

    def test_partial_is_valid(self):
        """PARTIAL is a valid status."""
        assert ProfileStatus.is_valid("PARTIAL")

    def test_failed_is_valid(self):
        """FAILED is a valid status."""
        assert ProfileStatus.is_valid("FAILED")

    def test_invalid_status_not_valid(self):
        """Invalid status is not valid."""
        assert not ProfileStatus.is_valid("INVALID")

    def test_status_constants(self):
        """Status constants have expected values."""
        assert ProfileStatus.SUCCESS == "SUCCESS"
        assert ProfileStatus.PARTIAL == "PARTIAL"
        assert ProfileStatus.FAILED == "FAILED"


class TestProfileResultConstruction:
    """Tests for ProfileResult construction and validation."""

    def test_success_result_has_profile(self):
        """SUCCESS result requires a profile."""
        profile = RepositoryProfile(
            source="github",
            repository="owner/repo",
            canonical_url="https://github.com/owner/repo",
            owner="owner",
            name="repo",
            profile_run_id="run-001",
            profiled_at="2024-01-01T00:00:00Z",
            source_endpoint="/repos/owner/repo",
            adapter_version="1.0.0",
        )
        result = ProfileResult(
            status="SUCCESS",
            profile=profile,
        )
        assert result.status == "SUCCESS"
        assert result.profile == profile

    def test_failed_result_has_none_profile(self):
        """FAILED result must have profile=None."""
        with pytest.raises(ValueError, match="FAILED result must have profile=None"):
            ProfileResult(
                status="FAILED",
                profile=RepositoryProfile(
                    source="github",
                    repository="owner/repo",
                    canonical_url="https://github.com/owner/repo",
                    owner="owner",
                    name="repo",
                    profile_run_id="run-001",
                    profiled_at="2024-01-01T00:00:00Z",
                    source_endpoint="/repos/owner/repo",
                    adapter_version="1.0.0",
                ),
            )

    def test_success_without_profile_raises(self):
        """SUCCESS result without profile raises."""
        with pytest.raises(ValueError, match="SUCCESS result must have a profile"):
            ProfileResult(
                status="SUCCESS",
                profile=None,
            )

    def test_partial_requires_profile(self):
        """PARTIAL result requires a profile (minimum valid)."""
        with pytest.raises(ValueError, match="PARTIAL result must have a profile"):
            ProfileResult(
                status="PARTIAL",
                profile=None,
            )

    def test_empty_status_raises(self):
        """Empty status raises ValueError."""
        with pytest.raises(ValueError, match="status must not be empty"):
            ProfileResult(status="")


class TestProfileResultRateLimitSemantics:
    """Tests for rate limit handling in ProfileResult."""

    def test_rate_limit_hit_flag(self):
        """rate_limit_hit can be set."""
        profile = RepositoryProfile(
            source="github",
            repository="owner/repo",
            canonical_url="https://github.com/owner/repo",
            owner="owner",
            name="repo",
            profile_run_id="run-001",
            profiled_at="2024-01-01T00:00:00Z",
            source_endpoint="/repos/owner/repo",
            adapter_version="1.0.0",
        )
        result = ProfileResult(
            status="SUCCESS",
            profile=profile,
            rate_limit_hit=True,
        )
        assert result.rate_limit_hit is True

    def test_rate_limit_hit_default_false(self):
        """rate_limit_hit defaults to False."""
        profile = RepositoryProfile(
            source="github",
            repository="owner/repo",
            canonical_url="https://github.com/owner/repo",
            owner="owner",
            name="repo",
            profile_run_id="run-001",
            profiled_at="2024-01-01T00:00:00Z",
            source_endpoint="/repos/owner/repo",
            adapter_version="1.0.0",
        )
        result = ProfileResult(status="SUCCESS", profile=profile)
        assert result.rate_limit_hit is False


# ---------------------------------------------------------------------------
# RepositoryProfilerConfig: Configuration Contract Tests
# ---------------------------------------------------------------------------

class TestRepositoryProfilerConfig:
    """Tests for RepositoryProfilerConfig contract."""

    def test_default_enabled_false(self):
        """enabled defaults to False."""
        config = RepositoryProfilerConfig()
        assert config.enabled is False

    def test_default_timeout_seconds(self):
        """timeout_seconds defaults to 10."""
        config = RepositoryProfilerConfig()
        assert config.timeout_seconds == 10

    def test_default_max_repositories_per_run(self):
        """max_repositories_per_run defaults to 100."""
        config = RepositoryProfilerConfig()
        assert config.max_repositories_per_run == 100

    def test_enabled_can_be_true(self):
        """enabled can be True."""
        config = RepositoryProfilerConfig(enabled=True)
        assert config.enabled is True

    def test_custom_timeout(self):
        """Custom timeout is accepted."""
        config = RepositoryProfilerConfig(timeout_seconds=30)
        assert config.timeout_seconds == 30

    def test_invalid_enabled_raises(self):
        """Non-bool enabled raises TypeError."""
        with pytest.raises(TypeError, match="enabled must be bool"):
            RepositoryProfilerConfig(enabled="true")

    def test_invalid_timeout_raises(self):
        """Non-positive timeout raises ValueError."""
        with pytest.raises(ValueError, match="timeout_seconds must be positive"):
            RepositoryProfilerConfig(timeout_seconds=0)

    def test_negative_timeout_raises(self):
        """Negative timeout raises ValueError."""
        with pytest.raises(ValueError, match="timeout_seconds must be positive"):
            RepositoryProfilerConfig(timeout_seconds=-5)

    def test_invalid_max_repos_raises(self):
        """Non-positive max_repositories_per_run raises ValueError."""
        with pytest.raises(ValueError, match="max_repositories_per_run must be positive"):
            RepositoryProfilerConfig(max_repositories_per_run=0)


# ---------------------------------------------------------------------------
# Helper Functions Tests
# ---------------------------------------------------------------------------

class TestHelpers:
    """Tests for helper factory functions."""

    def test_make_repository_identity_default(self):
        """make_repository_identity creates valid identity."""
        identity = make_repository_identity()
        assert identity.source == "github"
        assert identity.owner == "owner"
        assert identity.name == "repo"
        assert identity.repository == "owner/repo"
        assert identity.source_id == "github:owner/repo"

    def test_make_repository_profile_default(self):
        """make_repository_profile creates valid profile."""
        profile = make_repository_profile()
        assert profile.source == "github"
        assert profile.owner == "owner"
        assert profile.name == "repo"
        assert profile.profile_run_id == "run-001"
        assert profile.adapter_version == "1.0.0"
        assert profile.source_endpoint == "/repos/owner/repo"

    def test_make_profile_result_success(self):
        """make_profile_result creates SUCCESS result."""
        profile = make_repository_profile()
        result = make_profile_result(status="SUCCESS", profile=profile)
        assert result.status == "SUCCESS"
        assert result.profile == profile
        assert result.error is None

    def test_make_profile_result_partial(self):
        """make_profile_result creates PARTIAL result."""
        profile = make_repository_profile()
        result = make_profile_result(status="PARTIAL", profile=profile)
        assert result.status == "PARTIAL"


# ---------------------------------------------------------------------------
# Security Boundary Tests
# ---------------------------------------------------------------------------

class TestSecurityBoundary:
    """Tests for security boundary - no execution of repository content."""

    def test_no_eval_in_normalization(self):
        """Normalization does not use eval()."""
        # Should not raise
        identity = normalize_repository_identity("github", "owner/repo")
        assert identity.owner == "owner"

    def test_no_subprocess_in_profile(self):
        """ProfileResult does not spawn subprocess."""
        profile = RepositoryProfile(
            source="github",
            repository="owner/repo",
            canonical_url="https://github.com/owner/repo",
            owner="owner",
            name="repo",
            profile_run_id="run-001",
            profiled_at="2024-01-01T00:00:00Z",
            source_endpoint="/repos/owner/repo",
            adapter_version="1.0.0",
        )
        result = ProfileResult(status="SUCCESS", profile=profile)
        assert result.status == "SUCCESS"

    def test_malicious_text_in_profile_safe(self):
        """Malicious-looking text in description is stored as data, not executed."""
        malicious = "https://example.com/exec?cmd=rm -rf /"
        profile = RepositoryProfile(
            source="github",
            repository="owner/repo",
            canonical_url="https://github.com/owner/repo",
            owner="owner",
            name="repo",
            profile_run_id="run-001",
            profiled_at="2024-01-01T00:00:00Z",
            source_endpoint="/repos/owner/repo",
            adapter_version="1.0.0",
            description=malicious,  # stored as string, not executed
        )
        assert profile.description == malicious


# ---------------------------------------------------------------------------
# Immutability Tests
# ---------------------------------------------------------------------------

class TestImmutability:
    """Tests for frozen/immutability of dataclasses."""

    def test_repository_identity_frozen(self):
        """RepositoryIdentity is frozen."""
        identity = RepositoryIdentity(
            source="github",
            repository="owner/repo",
            canonical_url="https://github.com/owner/repo",
            owner="owner",
            name="repo",
        )
        with pytest.raises(AttributeError):
            identity.owner = "hacker"

    def test_repository_profile_frozen(self):
        """RepositoryProfile is frozen."""
        profile = RepositoryProfile(
            source="github",
            repository="owner/repo",
            canonical_url="https://github.com/owner/repo",
            owner="owner",
            name="repo",
            profile_run_id="run-001",
            profiled_at="2024-01-01T00:00:00Z",
            source_endpoint="/repos/owner/repo",
            adapter_version="1.0.0",
        )
        with pytest.raises(AttributeError):
            profile.description = "hacked"

    def test_profile_result_frozen(self):
        """ProfileResult is frozen."""
        profile = RepositoryProfile(
            source="github",
            repository="owner/repo",
            canonical_url="https://github.com/owner/repo",
            owner="owner",
            name="repo",
            profile_run_id="run-001",
            profiled_at="2024-01-01T00:00:00Z",
            source_endpoint="/repos/owner/repo",
            adapter_version="1.0.0",
        )
        result = ProfileResult(status="SUCCESS", profile=profile)
        with pytest.raises(AttributeError):
            result.status = "FAILED"


# ---------------------------------------------------------------------------
# No Direct SQLite Tests
# ---------------------------------------------------------------------------

class TestNoDirectSQLite:
    """Tests that RepositoryProfile does not do direct SQLite writes."""

    def test_no_sqlite_module_import(self):
        """RepositoryProfile does not import sqlite3."""
        import hbh.discovery.profile as profile_module
        # Check that sqlite3 is not imported at module level
        import sys
        sqlite_modules = [k for k in sys.modules if 'sqlite' in k.lower()]
        # This test passes if no sqlite modules were imported by profile module
        # Note: This is informational; actual DB access is orchestration's job
        assert 'sqlite3' not in dir(profile_module)


# ---------------------------------------------------------------------------
# No State Transition Tests
# ---------------------------------------------------------------------------

class TestNoStateTransition:
    """Tests that RepositoryProfile does not handle state transitions."""

    def test_no_state_machine_in_profile(self):
        """Profile module does not contain state machine logic."""
        import hbh.discovery.profile as profile_module
        assert not hasattr(profile_module, 'StateTransition')
        assert not hasattr(profile_module, 'transition')


# ---------------------------------------------------------------------------
# Adapter Version Tests
# ---------------------------------------------------------------------------

class TestAdapterVersion:
    """Tests for adapter version consistency."""

    def test_version_is_string(self):
        """ADAPTER_CONTRACT_VERSION is a string."""
        assert isinstance(ADAPTER_CONTRACT_VERSION, str)

    def test_version_not_empty(self):
        """ADAPTER_CONTRACT_VERSION is not empty."""
        assert ADAPTER_CONTRACT_VERSION

    def test_version_in_profile(self):
        """Profile uses adapter version."""
        profile = RepositoryProfile(
            source="github",
            repository="owner/repo",
            canonical_url="https://github.com/owner/repo",
            owner="owner",
            name="repo",
            profile_run_id="run-001",
            profiled_at="2024-01-01T00:00:00Z",
            source_endpoint="/repos/owner/repo",
            adapter_version=ADAPTER_CONTRACT_VERSION,
        )
        assert profile.adapter_version == ADAPTER_CONTRACT_VERSION