"""
HBH Repository Profiler Integration — RP-2 persistence layer.

Handles atomic persistence of repository profiling results (Unit C output):

1. Insert into repository_profiles
2. Insert into profile_runs
3. Update repositories.profile_status

All three operations run in a single SQLite transaction (BEGIN -> COMMIT / ROLLBACK).
Audit logging is deliberately excluded from this transaction and is performed
after the transaction closes, per the integration contract (§11.2, §12).

The function is called by the orchestrator after RepositoryProfiler.profile(...)
returns a ProfileResult.

Fail-closed:
  - If any of the three mandatory writes fails, the whole transaction is rolled
    back and the function returns False.
  - If ROLLBACK itself fails, the function returns False and the caller should
    treat persistence as "tidak dapat dipastikan" (cannot be confirmed).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any, Optional

from hbh.core.audit import log
from hbh.core.database import Database, insert_event
from hbh.discovery.profile import (
    ProfileResult,
    RepositoryIdentity,
    RepositoryProfile,
    ProfileStatus,
)

# ---------------------------------------------------------------------------
# Audit events — definitif dari kontrak 5 (rp-2-integration-contract.md).
#
#      Event                    | Pesan                             | Actor                         | Entity_id
#   -------------------------------------------------------------------------------------------
#   profile_run_started        | profil run dimulai                | repository_profiler_integration | profile_run_id
#   profile_run_completed      | profil selesai (SUCCESS/PARTIAL)  | repository_profiler_integration | profile_run_id
#   profile_run_failed         | profil gagal                      | repository_profiler_integration | profile_run_id
#   profile_persisted          | data profil tersimpan             | database_integration            | profile_run_id
#
# Mekanisme:
#   - stderr        : log(event=...) yang sudah ada di audit.py
#   - events table  : insert_event() saja, dan HANYA setelah transaksi utama
#                     ditutup (COMMIT atau ROLLBACK) — kontrak 11.1, 12B.2
#   - Jangan tambah metode baru di audit.py.
#   - Tidak ada "event kelima"; kontrak 5 hanya mendefinisikan empat event di atas.
# ---------------------------------------------------------------------------
_PROFILING_EVENTS: dict[str, tuple[str, str]] = {
    "profile_run_started": ("profil run dimulai", "repository_profiler_integration"),
    "profile_run_completed": ("profil selesai (SUCCESS/PARTIAL)", "repository_profiler_integration"),
    "profile_run_failed": ("profil gagal", "repository_profiler_integration"),
    "profile_persisted": ("data profil tersimpan", "database_integration"),
}

# Operational-failure notice yang ditulis setelah ROLLBACK (kontrak 12B.1/12B.3).
# Catatan ini bersifat best-effort dan BUKAN salah satu dari empat event kontrak.
_OPERATIONAL_FAILURE_EVENT = "operational_failure"
_OPERATIONAL_FAILURE_MESSAGE = "transaksi utama gagal; persistensi tidak dapat dipastikan"


def _emit_profile_event(db: Database, event: str, entity_id: str,
                        *, record_events: bool) -> None:
    """Emit one profiling audit event.

    Always writes to stderr via log() (no commit). When record_events is True,
    also writes to the events table via insert_event(). The caller must
    guarantee the main transaction is closed (COMMIT or ROLLBACK) before
    calling with record_events=True (contract 11.1, 12B.2).

    Best-effort; never changes the persistence decision.
    """
    message, actor = _PROFILING_EVENTS[event]
    # 1) stderr (best-effort). A stderr failure is reported separately and
    #    NEVER changes the persistence outcome (contract 13, scenario 9).
    try:
        log(level="INFO", event=event, message=message,
            actor=actor, entity_id=entity_id)
    except Exception:
        try:
            log(level="ERROR", event="audit_error",
                message="catatan ke stderr gagal; persistensi tidak terpengaruh",
                actor=actor, entity_id=entity_id)
        except Exception:
            pass

    # 2) events table — only when record_events is True (caller guarantees the
    #    main transaction is already closed; contract 11.1, 12B.2).
    if record_events:
        try:
            insert_event(
                db,
                entity_id=entity_id,
                actor=actor,
                reason=message,
                from_state=None,
                to_state=None,
                metadata=None,
            )
        except Exception:
            try:
                log(level="ERROR", event="audit_error",
                    message=f"catatan audit gagal untuk event={event}; persistensi tidak terpengaruh",
                    actor=actor, entity_id=entity_id)
            except Exception:
                pass


def _record_operational_failure(db: Database, entity_id: str) -> None:
    """Best-effort operational-failure note after the main transaction
    has been rolled back (contract 12B.1/12B.3).

    Writes to stderr (log) and, when safe, to the events table (insert_event).
    Never changes the persistence outcome. Contract: only AFTER ROLLBACK closes.
    """
    # 1) stderr (best-effort). A stderr failure is reported separately and
    #    NEVER changes the persistence outcome (contract 13, scenario 9).
    try:
        log(level="WARN", event=_OPERATIONAL_FAILURE_EVENT,
            message=_OPERATIONAL_FAILURE_MESSAGE,
            actor="repository_profiler_integration", entity_id=entity_id)
    except Exception:
        try:
            log(level="ERROR", event="audit_error",
                message="catatan operasional gagal; persistensi tidak terpengaruh",
                actor="repository_profiler_integration", entity_id=entity_id)
        except Exception:
            pass

    # 2) events table (best-effort), only if the database handle is usable.
    #    The caller guarantees this is called AFTER ROLLBACK closes.
    try:
        insert_event(
            db,
            entity_id=entity_id,
            actor="repository_profiler_integration",
            reason=_OPERATIONAL_FAILURE_MESSAGE,
            from_state=None,
            to_state=None,
            metadata=None,
        )
    except Exception:
        try:
            log(level="ERROR", event="audit_error",
                message="catatan kegagalan operasional gagal ditulis ke events",
                actor="repository_profiler_integration", entity_id=entity_id)
        except Exception:
            pass


def _emit_profile_events(db: Database, events: list[tuple[str, str]],
                         record_events: bool) -> None:
    """Emit several profiling events (SUCCESS/PARTIAL/FAILED path)."""
    for event, entity_id in events:
        _emit_profile_event(db, event, entity_id, record_events=record_events)


def _profile_to_dict(profile: RepositoryProfile) -> dict[str, Any]:
    """Serialize a RepositoryProfile into a JSON-serializable dict."""
    return {
        "source": profile.source,
        "repository": profile.repository,
        "canonical_url": profile.canonical_url,
        "owner": profile.owner,
        "name": profile.name,
        "profile_run_id": profile.profile_run_id,
        "profiled_at": profile.profiled_at,
        "source_endpoint": profile.source_endpoint,
        "adapter_version": profile.adapter_version,
        "raw_payload_reference": profile.raw_payload_reference,
        "raw_payload_hash": profile.raw_payload_hash,
        "visibility": profile.visibility,
        "archived": profile.archived,
        "fork": profile.fork,
        "default_branch": profile.default_branch,
        "description": profile.description,
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
        "pushed_at": profile.pushed_at,
        "size_kb": profile.size_kb,
        "primary_language": profile.primary_language,
        "language_breakdown": profile.language_breakdown,
        "license_detected": profile.license_detected,
        "license_spdx_id": profile.license_spdx_id,
        "license_name": profile.license_name,
        "open_issues_count": profile.open_issues_count,
        "stars": profile.stars,
        "forks_count": profile.forks_count,
        "watchers": profile.watchers,
    }


def _repo_id(profile: Optional[RepositoryProfile]) -> Optional[str]:
    """Construct the repository id for the repositories table."""
    if profile is None:
        return None
    return f"{profile.source}:{profile.owner}/{profile.name}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Public API — record_profile_run
# ---------------------------------------------------------------------------


def record_profile_run(
    db: Database,
    profile_result: ProfileResult,
    profile_run_id: str,
    *,
    discovery_run_id: Optional[str] = None,
    repository_identity: Optional[RepositoryIdentity] = None,
    post_commit_hooks: Optional[list[callable]] = None,
) -> bool:
    """
    Persist a profile run atomically.

    Arguments:
        db: Open SQLite Database handle.
        profile_result: ProfileResult from RepositoryProfiler.profile(...).
        profile_run_id: Unique id of this profile run.
        discovery_run_id: Optional discovery run id. NULL / None -> stored as NULL
            (direct profiling outside a discovery run, per contract §6).
        repository_identity: Optional RepositoryIdentity supplied by the caller
            (e.g. orchestrator) before RepositoryProfiler.profile() was called.
            If the profiling result carries no RepositoryProfile (FAILED), this
            identity is used to derive repo_id for updating
            repositories.profile_status.
        post_commit_hooks: Optional list of zero-argument callbacks run after the
            transaction is closed. Failure is reported via stderr and never
            changes the persistence outcome.

    Returns:
        True if all three mandatory writes succeeded and COMMIT was made.
        False if any write failed and ROLLBACK was completed (persistence
        cannot be confirmed).

    Contract:
        - Sections 3.1, 3.2, 7.2, 11.1, 11.2, 12, 12B, 13 of
          rp-2-integration-contract.md.
    """
    profile = profile_result.profile

    # ---- Determine persisted values --------------------------------------
    if profile is not None:
        rp = profile
        profile_data_json: Optional[str] = json.dumps(
            _profile_to_dict(rp), default=str
        )
        profiled_at: Optional[str] = rp.profiled_at
        repo_id: Optional[str] = _repo_id(rp)
    else:
        # FAILED result: no RepositoryProfile. profile_data NULL.
        profile_data_json = None
        # profiled_at is NOT NULL in repository_profiles, so use now for
        # failed runs too (the time when the profiling attempt finished).
        profiled_at = _now_iso()
        # If repository_identity is provided, derive repo_id from it so that
        # repositories.profile_status can be updated per contract §7.2/§7.3 even
        # when RepositoryProfile is absent. Without identity, repo_id stays None
        # and the update is not performed (fail closed).
        if repository_identity is not None:
            repo_id = f"{repository_identity.source}:{repository_identity.owner}/{repository_identity.name}"
        else:
            repo_id = None
    rp = profile  # may be None for FAILED; used in INSERTs below

    # ---- Phase 0: profile_run_started (before the main transaction) -------
    # No main transaction is open yet, so both stderr and events-table writes
    # are safe. If the caller already owns a transaction, we skip the
    # events-table write per contract 11.1 (audit inside the open tx forbidden).
    started_record_events = not db.connection.in_transaction
    _emit_profile_event(
        db,
        "profile_run_started",
        profile_run_id,
        record_events=started_record_events,
    )

    # ---- Start the mandatory transaction (owner of BEGIN/COMMIT/ROLLBACK) -
    if db.connection.in_transaction:
        # A transaction is already active (e.g. from the caller's context).
        # Do not start a nested transaction.
        already_in_tx = True
    else:
        db.connection.execute("BEGIN")
        already_in_tx = False

    try:
        # When both profile and repository_identity are available, verify they are
        # mutually consistent. A conflict means the caller provided two different
        # identities for the same run; refusing to proceed keeps us from updating
        # one repository while persisting another's profile.
        if profile is not None and repository_identity is not None:
            identity_repo_id = f"{repository_identity.source}:{repository_identity.owner}/{repository_identity.name}"
            profile_repo_id = _repo_id(profile)
            if identity_repo_id != profile_repo_id:
                raise RuntimeError(
                    f"identity conflict: repository_identity ({identity_repo_id}) "
                    f"inconsistent with profile ({profile_repo_id})"
                )

        # 1. Insert repository_profiles
        db.connection.execute(
            """
            INSERT INTO repository_profiles
                (profile_run_id, discovery_run_id, source, repository,
                 canonical_url, owner, name, profiled_at, source_endpoint,
                 adapter_version, raw_payload_reference, raw_payload_hash,
                 status, profile_data, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_run_id,
                discovery_run_id,
                rp.source if rp else None,
                rp.repository if rp else None,
                rp.canonical_url if rp else None,
                rp.owner if rp else None,
                rp.name if rp else None,
                profiled_at,
                rp.source_endpoint if rp else None,
                rp.adapter_version if rp else None,
                rp.raw_payload_reference if rp else None,
                rp.raw_payload_hash if rp else None,
                profile_result.status,
                profile_data_json,
                _now_iso(),
            ),
        )

        # 2. Insert profile_runs
        db.connection.execute(
            """
            INSERT INTO profile_runs
                (profile_run_id, discovery_run_id, start_profiling_at,
                 end_profiling_at, status, error_summary, repository_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_run_id,
                discovery_run_id,
                None,  # start_profiling_at - caller may update later
                profiled_at,  # end profiling time (from profile or now for FAILED)
                profile_result.status,
                profile_result.error,
                1,  # repository_count = 1 per profile_run_id
            ),
        )

        # 3. Update repositories.profile_status
        #    Contract §7.2: SUCCESS->profiled, PARTIAL->partial, FAILED->failed
        if repo_id is not None:
            mapped_status: str
            if profile_result.status == ProfileStatus.SUCCESS:
                mapped_status = "profiled"
            elif profile_result.status == ProfileStatus.PARTIAL:
                mapped_status = "partial"
            else:
                mapped_status = "failed"
            cursor = db.connection.execute(
                "UPDATE repositories SET profile_status = ? WHERE repo_id = ?",
                (mapped_status, repo_id),
            )
            if cursor.rowcount == 0:
                # No matching repository row: persistence cannot be confirmed.
                # Fail closed; do not commit.
                raise RuntimeError(
                    f"repository row not found for repo_id={repo_id!r}; "
                    "persistence cannot be confirmed"
                )
        else:
            # Identity not available: do not fabricate identity; persistence
            # cannot be confirmed. Fail closed.
            raise RuntimeError(
                "repository identity unavailable for this profile; "
                "persistence cannot be confirmed"
            )

        # ---- All mandatory writes succeeded: COMMIT ------------------------
        db.connection.commit()
        # Post-commit hooks: run after the transaction is closed so that a
        # failure in any hook is reported separately and never rolls back the
        # persistence outcome.  The caller (orchestrator) is responsible for
        # keeping these hooks idempotent and for treating a hook failure as a
        # separate, best-effort audit/operational notice (contract §12).
        if post_commit_hooks:
            for hook in post_commit_hooks:
                try:
                    hook()
                except Exception as exc:
                    _sys = sys
                    _sys.stderr.write(
                        f"post-commit hook failed for run {profile_run_id}: "
                        f"{exc!r}\n"
                    )

        # ---- After COMMIT (main transaction closed): audit events ---------
        # JANGAN memanggil insert_event() SEMENTARA transaksi utama masih terbuka.
        # Saat ini transaksi sudah COMMIT, jadi events-table OK.
        _emit_profile_events(
            db,
            [
                (
                    "profile_run_completed"
                    if profile_result.status
                        in (ProfileStatus.SUCCESS, ProfileStatus.PARTIAL)
                    else "profile_run_failed",
                    profile_run_id,
                ),
                ("profile_persisted", profile_run_id),
            ],
            record_events=True,
        )

        # All mandatory writes succeeded: COMMIT succeeded.
        return True

    except Exception:
        # Any mandatory write failed: ROLLBACK everything.
        try:
            db.connection.rollback()
        except Exception:
            pass
        # After ROLLBACK, record the operational failure (best-effort).
        # Contract 12B.1/12B.3: this never changes the persistence outcome.
        _record_operational_failure(db, profile_run_id)
        return False
