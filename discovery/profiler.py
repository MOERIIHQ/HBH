"""
HBH Repository Profiler - RP-2 Unit C.

Single-repository profiling orchestrator.

Composes:
  RP-2 Unit B -> hbh.discovery.profile.build_profile_run_context(...)
  RP-2 Unit A -> hbh.discovery.github.metadata_adapter.GitHubMetadataAdapter.profile(...)

Produces one isolatable ProfileResult per repository. This component does NOT:
  - open HTTP connections itself (Unit A does)
  - write SQLite / transition state machine / emit audit events
  - persist raw evidence (Unit A does, through injected RawStorage)
  - retry, sleep, or backoff
  - score, rank, recommend, clone, or execute anything

Dependency injection:
  RepositoryProfiler is wired with the Unit A adapter itself
  (GitHubMetadataAdapter), not with GitHubHTTPClient/RawStorage. The
  profiler therefore only depends on one stable interface (.profile) and
  can never create a duplicate transport or storage layer just to build
  its own adapter.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from hbh.discovery.github.metadata_adapter import GitHubMetadataAdapter
from hbh.discovery.profile import (
    ProfileResult,
    ProfileRunContext,
    RepositoryIdentity,
    build_profile_run_context,
)


class RepositoryProfiler:
    """Orchestrates a single repository profile operation (Unit C).

    Responsibilities:
      - build a ProfileRunContext via the Unit B factory
      - delegate the actual GitHub metadata fetch + normalization to Unit A
      - return the resulting ProfileResult without modification

    Args:
        github_metadata_adapter: The Unit A adapter. Injected once; the
            profiler holds a shared reference (no per-call construction).
    """

    def __init__(self, github_metadata_adapter: GitHubMetadataAdapter) -> None:
        self._adapter = github_metadata_adapter

    def profile(
        self,
        repository_identity: RepositoryIdentity,
        profile_run_id: str,
        started_at: Optional[datetime] = None,
        source_config: Optional[dict[str, Any]] = None,
    ) -> ProfileResult:
        """Profile one repository in a single, testable operation.

        Pipeline:
          1. build ProfileRunContext (Unit B contract)
          2. GitHubMetadataAdapter.profile(repository_identity, run_context)

        Provenance (raw_payload_reference / raw_payload_hash, adapter_version,
        profiled_at) is produced by Unit A as part of its own contract; the
        profiler does not compute or fabricate it.

        Args:
            repository_identity: Canonical repository identity supplied by the
                caller (e.g. source/owner/repo). Not synthesized here.
            profile_run_id: Caller-supplied run id. Never generated here.
            started_at: Optional aware datetime. None -> UTC now (Unit B).
            source_config: Optional source config dict. None -> {} (Unit B).

        Returns:
            ProfileResult from the adapter, used as-is. Failed results carry
            profile=None and are not disguised.
        """
        run_context = build_profile_run_context(
            profile_run_id=profile_run_id,
            repository=repository_identity,
            started_at=started_at,
            source_config=source_config,
        )

        return self._adapter.profile(
            repository_identity=repository_identity,
            run_context=run_context,
        )
