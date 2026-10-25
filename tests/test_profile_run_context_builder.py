"""
Test for hbh.discovery.profile.build_profile_run_context (RP-2 Unit B).

Kontrak:
- profile_run_id: wajib, string yang tidak kosong.
- repository: instance RepositoryIdentity yang valid.
- started_at: tidak diberikan -> timestamp UTC otomatis; diberikan -> disimpan apa adanya.
- source_config=None berarti kosong; bukan dict -> ditolak.
- Mengembalikan ProfileRunContext yang sudah ada; immutable (frozen).

Catatan: perubahan hanya pada modul factory (hbh/discovery/profile.py) dan
file uji ini. Tidak mengubah RP-1, GH-3B, Unit A, SQLite, registry, runtime,
CLI, lifecycle, atau identitas Git.
"""

from datetime import datetime, timezone

import pytest

from hbh.discovery.profile import (
    ProfileRunContext,
    RepositoryIdentity,
    build_profile_run_context,
    make_repository_identity,
)


class TestBuildProfileRunContext:
    """Konstruksi dengan semua input eksplisit."""

    def test_all_inputs_explicit(self):
        now = datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone.utc)
        repository = make_repository_identity(
            source="github", owner="octocat", name="Hello-World"
        )
        config = {"github": {"enabled": True}, "max_repositories": 5}

        ctx = build_profile_run_context(
            profile_run_id="run-001",
            repository=repository,
            started_at=now,
            source_config=config,
        )

        assert isinstance(ctx, ProfileRunContext)
        assert type(ctx) is ProfileRunContext
        assert ctx.profile_run_id == "run-001"
        assert ctx.started_at == now
        assert ctx.repository is repository
        assert ctx.source_config == config
        assert ctx.source_config is config

    def test_auto_utc_timestamp_when_started_at_not_provided(self):
        before = datetime.now(timezone.utc)

        ctx = build_profile_run_context(
            profile_run_id="run-001",
            repository=make_repository_identity(),
        )

        after = datetime.now(timezone.utc)
        assert before <= ctx.started_at <= after
        assert ctx.started_at.tzinfo is not None
        assert ctx.started_at.utcoffset().total_seconds() == 0

    def test_explicit_timestamp_preserved_as_given(self):
        given = datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone.utc)

        ctx = build_profile_run_context(
            profile_run_id="run-001",
            repository=make_repository_identity(),
            started_at=given,
        )

        assert ctx.started_at == given
        assert ctx.started_at is given

    def test_repository_identity_preserved(self):
        repository = make_repository_identity(
            source="github", owner="octocat", name="Hello-World"
        )

        ctx = build_profile_run_context("run-001", repository)

        assert ctx.repository is repository

    def test_empty_profile_run_id_rejected(self):
        with pytest.raises(ValueError, match="profile_run_id must be a non-empty string"):
            build_profile_run_context("", make_repository_identity())

    def test_none_profile_run_id_rejected(self):
        with pytest.raises(ValueError, match="profile_run_id must be a non-empty string"):
            build_profile_run_context(None, make_repository_identity())

    def test_non_string_profile_run_id_rejected(self):
        with pytest.raises(ValueError, match="profile_run_id must be a non-empty string"):
            build_profile_run_context(12345, make_repository_identity())

    def test_repository_not_instance_rejected(self):
        with pytest.raises(ValueError, match="repository must be an instance of RepositoryIdentity"):
            build_profile_run_context("run-001", repository="octocat/Hello-World")

    def test_repository_none_rejected(self):
        with pytest.raises(ValueError, match="repository must be an instance of RepositoryIdentity"):
            build_profile_run_context("run-001", repository=None)

    def test_source_config_none_becomes_empty_dict(self):
        ctx = build_profile_run_context("run-001", make_repository_identity())

        assert ctx.source_config == {}

    def test_source_config_valid_dict_preserved(self):
        config = {"github": {"enabled": True}, "max_repositories": 5}

        ctx = build_profile_run_context(
            "run-001",
            make_repository_identity(),
            source_config=config,
        )

        assert ctx.source_config == config
        assert ctx.source_config is config

    def test_source_config_wrong_type_rejected(self):
        with pytest.raises(ValueError, match="source_config must be a dict or None"):
            build_profile_run_context(
                "run-001",
                make_repository_identity(),
                source_config=["hanya list"],
            )

    def test_result_is_immutable(self):
        ctx = build_profile_run_context("run-001", make_repository_identity())

        with pytest.raises(AttributeError):
            ctx.profile_run_id = "hacked"

    def test_single_space_profile_run_id_rejected(self):
        with pytest.raises(ValueError, match="profile_run_id must be a non-empty string"):
            build_profile_run_context(" ", make_repository_identity())

    def test_multiple_spaces_profile_run_id_rejected(self):
        with pytest.raises(ValueError, match="profile_run_id must be a non-empty string"):
            build_profile_run_context("   ", make_repository_identity())

    def test_tab_profile_run_id_rejected(self):
        with pytest.raises(ValueError, match="profile_run_id must be a non-empty string"):
            build_profile_run_context("\t", make_repository_identity())

    def test_whitespace_only_profile_run_id_rejected(self):
        with pytest.raises(ValueError, match="profile_run_id must be a non-empty string"):
            build_profile_run_context(" \t\n ", make_repository_identity())

    def test_valid_id_with_leading_trailing_spaces_preserved(self):
        ctx = build_profile_run_context("  my repo  ", make_repository_identity())
        assert ctx.profile_run_id == "  my repo  "

    def test_no_global_state_across_builds(self):
        first = build_profile_run_context("run-001", make_repository_identity())
        second = build_profile_run_context("run-002", make_repository_identity())

        assert first.profile_run_id == "run-001"
        assert second.profile_run_id == "run-002"
