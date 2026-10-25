"""
HBH Repository Profiler — GitHub Metadata Adapter (RP-2 Unit A).

Produces a deterministic RepositoryProfile for a GitHub repository using:

    GET /repos/{owner}/{repo}

This module is a metadata adapter only. It does NOT implement the
DiscoveryAdapter contract (which returns BountyCandidate) and does NOT
perform persistence, state transition, scoring, cloning, or network access
inside the model.

Dependencies are injected explicitly:
- GitHubHTTPClient (transport, authentication, timeout)
- RawStorage (content-addressed raw evidence storage)

Contract (frozen RP-1 specification):
- SUCCESS : 2xx + valid JSON object -> RepositoryProfile
- FAILED  : 401 / 403 / 404 / 429 / 5xx, network error, timeout,
            malformed JSON, or unexpected schema (profile=None)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict

from hbh.discovery.github.http_client import (
    GitHubHTTPClient,
    GitHubHTTPError,
    GitHubHTTPResponse,
)
from hbh.discovery.profile import (
    ADAPTER_CONTRACT_VERSION,
    ProfileResult,
    ProfileStatus,
    ProfileRunContext,
    RepositoryIdentity,
    RepositoryProfile,
    make_profile_result,
)
from hbh.discovery.raw_storage import RawStorage, RawStorageError


# Adapter contract version — per RP-SPEC section 7.8 example "1.0.0".
ADAPTER_CONTRACT_VERSION: str = "1.0.0"


def _identity_is_valid(identity: RepositoryIdentity) -> bool:
    """Lightweight guard for a RepositoryIdentity consumed by the adapter."""
    if identity is None or not isinstance(identity, RepositoryIdentity):
        return False
    if not identity.source or not identity.owner or not identity.name or not identity.repository:
        return False
    if not identity.canonical_url.startswith("https://"):
        return False
    return True


class GitHubMetadataAdapter:
    """Produces a RepositoryProfile from GitHub repository metadata.

    Constructor dependencies are injected explicitly so the adapter does not
    create its own HTTP client, database connection, or storage.
    """

    def __init__(self, http_client: GitHubHTTPClient, raw_storage: RawStorage) -> None:
        self._http_client = http_client
        self._raw_storage = raw_storage

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def profile(
        self,
        repository_identity: RepositoryIdentity,
        run_context: ProfileRunContext,
    ) -> ProfileResult:
        """Profile one GitHub repository.

        Args:
            repository_identity: Canonical repository identity (source/repository).
            run_context: Profile run context (profile_run_id..., repository).

        Returns:
            ProfileResult wrapping a RepositoryProfile (SUCCESS/PARTIAL) or a
            FAILED result with profile=None.
        """
        if not _identity_is_valid(repository_identity):
            return self._failed(
                "invalid repository identity: source, repository, owner and "
                "name are required and canonical_url must be https://"
            )
        if not run_context or not run_context.profile_run_id:
            return self._failed("missing profile run id in run context")

        path = f"/repos/{repository_identity.owner}/{repository_identity.name}"

        try:
            response = self._http_client.request(path, params=None)
        except GitHubHTTPError as exc:
            return self._failed(f"GitHub transport error for {path}: {exc}")

        return self._result_for_status(
            response, repository_identity, run_context
        )

    # ------------------------------------------------------------------
    # Status handling (per RP-SPEC section 17)
    # ------------------------------------------------------------------
    def _result_for_status(
        self,
        response: GitHubHTTPResponse,
        repository_identity: RepositoryIdentity,
        run_context: ProfileRunContext,
    ) -> ProfileResult:
        status_code = response.status_code

        if status_code == 200:
            return self._success(repository_identity, response.body, run_context)

        if status_code == 404:
            return self._failed("repository not found (404)")

        if status_code == 401:
            return self._failed("authentication failed (401)")

        if status_code == 403:
            return self._failed("forbidden (403)")

        if status_code == 429:
            return self._failed("rate limited (429)", rate_limit_hit=True)

        if 500 <= status_code < 600:
            return self._failed(f"server error ({status_code})")

        # No retry/backoff/sleep is performed above; undefined statuses are
        # reported as FAILED rather than inventing new semantics.
        return self._failed(f"unexpected HTTP status {status_code}")

    def _success(
        self,
        repository_identity: RepositoryIdentity,
        raw_body: bytes,
        run_context: ProfileRunContext,
    ) -> ProfileResult:
        try:
            payload = self._parse_payload(raw_body)
            raw_ref, raw_hash = self._store_evidence(payload)
            profile = self._build_profile(
                repository_identity, payload, run_context, raw_ref, raw_hash
            )
        except ValueError as exc:
            return self._failed(f"repository metadata malformed: {exc}")
        except RawStorageError as exc:
            return self._failed(f"raw evidence storage failed: {exc}")

        return make_profile_result(
            status=ProfileStatus.SUCCESS,
            profile=profile,
            error=None,
        )

    # ------------------------------------------------------------------
    # Payload helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_payload(raw_body: bytes) -> Dict[str, Any]:
        if not raw_body:
            raise ValueError("Empty response body from GitHub")
        try:
            text = raw_body.decode("utf-8")
            payload = json.loads(text)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError(f"Malformed repository metadata payload: {exc}") from exc

        if not isinstance(payload, dict):
            raise ValueError(
                f"Expected a GitHub repository JSON object, got {type(payload).__name__}"
            )
        return payload

    def _store_evidence(self, payload: Dict[str, Any]) -> tuple[str, str]:
        # The adapter never reconstructs evidence from a profile; it hands the
        # parsed GitHub payload (the actual API source) to RawStorage, which
        # SHA-256 canonicalizes the JSON.  That SHA is NOT a hash of the raw
        # HTTP bytes.
        return self._raw_storage.store("github", payload)

    def _build_profile(
        self,
        repository_identity: RepositoryIdentity,
        payload: Dict[str, Any],
        run_context: ProfileRunContext,
        raw_ref: str,
        raw_hash: str,
    ) -> RepositoryProfile:
        license_obj = payload.get("license")
        if isinstance(license_obj, dict):
            license_detected = True
            license_spdx_id = license_obj.get("spdx_id")
            license_name = license_obj.get("name")
        else:
            license_detected = False
            license_spdx_id = None
            license_name = None

        try:
            return RepositoryProfile(
                source=repository_identity.source,
                repository=repository_identity.repository,
                canonical_url=repository_identity.canonical_url,
                owner=repository_identity.owner,
                name=repository_identity.name,
                profile_run_id=run_context.profile_run_id,
                profiled_at=self._now_iso(),
                source_endpoint=self._source_endpoint(repository_identity),
                adapter_version=ADAPTER_CONTRACT_VERSION,
                raw_payload_reference=raw_ref,
                raw_payload_hash=raw_hash,
                visibility=payload.get("visibility"),
                archived=payload.get("archived"),
                fork=payload.get("fork"),
                default_branch=payload.get("default_branch"),
                description=payload.get("description"),
                created_at=payload.get("created_at"),
                updated_at=payload.get("updated_at"),
                pushed_at=payload.get("pushed_at"),
                size_kb=payload.get("size"),
                primary_language=payload.get("language"),
                # V1 single endpoint does not return a language breakdown
                # (spec section 8.2 — future extension only).
                language_breakdown=None,
                license_detected=license_detected,
                license_spdx_id=license_spdx_id,
                license_name=license_name,
                open_issues_count=payload.get("open_issues_count"),
                stars=payload.get("stargazers_count"),
                forks_count=payload.get("forks_count"),
                watchers=payload.get("watchers_count"),
            )
        except TypeError as exc:
            # RepositoryProfile is the contract authority for optional-field
            # types.  If a supplied metadata field violates the contract, fail
            # closed rather than fabricate a valid-looking profile.
            raise ValueError(f"repository metadata field violates RP-1 contract: {exc}") from exc

    # ------------------------------------------------------------------
    # Fail-closed helpers
    # ------------------------------------------------------------------
    def _failed(self, message: str, *, rate_limit_hit: bool = False) -> ProfileResult:
        return make_profile_result(
            status=ProfileStatus.FAILED,
            profile=None,
            error=message,
            rate_limit_hit=rate_limit_hit,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _source_endpoint(repository_identity: RepositoryIdentity) -> str:
        return f"/repos/{repository_identity.owner}/{repository_identity.name}"
