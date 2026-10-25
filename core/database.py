"""
HBH Database — Phase 0 + Discovery extension.

SQLite single source of truth. Schema v1 with 5 core domain tables +
events/audit log. Extended with discovery schema (v2).

No external service dependency.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from hbh.core.config import Config

SCHEMA_VERSION: int = 3
_SUPPORTED_SCHEMA_VERSIONS: frozenset[int] = frozenset({1, 2, 3})

# ---------------------------------------------------------------------------
# Schema DDL (v1 — unchanged from Phase 0)
# ---------------------------------------------------------------------------

_CREATE_TABLES: str = """
CREATE TABLE IF NOT EXISTS schema_versions (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bounties (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    reward TEXT,
    created_at TEXT,
    discovered_at TEXT,
    status TEXT NOT NULL DEFAULT 'unknown'
);

CREATE TABLE IF NOT EXISTS repositories (
    repo_id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    size_kb INTEGER,
    language TEXT,
    default_branch TEXT,
    last_push TEXT,
    has_lfs INTEGER NOT NULL DEFAULT 0,
    profile_status TEXT NOT NULL DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS triage (
    bounty_id TEXT PRIMARY KEY,
    complexity REAL,
    competition REAL,
    feasibility REAL,
    risk REAL,
    estimated_cost REAL,
    expected_value REAL,
    decision TEXT,
    FOREIGN KEY (bounty_id) REFERENCES bounties(id)
);

CREATE TABLE IF NOT EXISTS executions (
    execution_id TEXT PRIMARY KEY,
    bounty_id TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    failure_reason TEXT,
    api_cost REAL DEFAULT 0,
    network_bytes INTEGER DEFAULT 0,
    diff_lines INTEGER DEFAULT 0,
    FOREIGN KEY (bounty_id) REFERENCES bounties(id)
);

CREATE TABLE IF NOT EXISTS outcomes (
    bounty_id TEXT PRIMARY KEY,
    validation_status TEXT NOT NULL DEFAULT 'pending',
    pr_status TEXT NOT NULL DEFAULT 'none',
    human_intervention INTEGER NOT NULL DEFAULT 0,
    final_result TEXT,
    FOREIGN KEY (bounty_id) REFERENCES bounties(id)
);

CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT,
    actor TEXT NOT NULL,
    reason TEXT,
    timestamp TEXT NOT NULL,
    metadata TEXT
);
"""

# ---------------------------------------------------------------------------
# Discovery schema extension (v2 — additive migration)
# ---------------------------------------------------------------------------

# Columns to add to bounties table (additive, nullable)
_BOUNTIES_DISCOVERY_COLUMNS: list[str] = [
    "source TEXT",
    "source_id TEXT",
    "canonical_issue_key TEXT",
    "repository_url TEXT",
    "issue_url TEXT",
    "currency TEXT",
    "source_created_at TEXT",
    "source_updated_at TEXT",
    "last_activity TEXT",
    "state TEXT",
    "labels TEXT",
    "raw_payload_reference TEXT",
    "raw_payload_hash TEXT",
    "adapter_version TEXT",
    "discovery_run_id TEXT",
]

# New table: discovery_runs
_CREATE_DISCOVERY_RUNS: str = """
CREATE TABLE IF NOT EXISTS discovery_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'RUNNING',
    trigger TEXT,
    adapters_total INTEGER NOT NULL DEFAULT 0,
    adapters_succeeded INTEGER NOT NULL DEFAULT 0,
    adapters_failed INTEGER NOT NULL DEFAULT 0,
    candidates_found INTEGER NOT NULL DEFAULT 0,
    candidates_inserted INTEGER NOT NULL DEFAULT 0,
    candidates_duplicate INTEGER NOT NULL DEFAULT 0,
    error_summary TEXT
);
"""

# Index for fast lookup of candidates by source + source_id
_CREATE_BOUNTIES_SOURCE_ID_INDEX: str = """
CREATE INDEX IF NOT EXISTS idx_bounties_source_source_id
    ON bounties (source, source_id);
"""

# ---------------------------------------------------------------------------
# Repository profiling schema extension (v3 — additive migration)
# ---------------------------------------------------------------------------

# New table: repository_profiles
_CREATE_REPOSITORY_PROFILES: str = """
CREATE TABLE IF NOT EXISTS repository_profiles (
    profile_run_id TEXT PRIMARY KEY,
    discovery_run_id TEXT,
    source TEXT,
    repository TEXT,
    canonical_url TEXT,
    owner TEXT,
    name TEXT,
    profiled_at TEXT NOT NULL,
    source_endpoint TEXT,
    adapter_version TEXT,
    raw_payload_reference TEXT,
    raw_payload_hash TEXT,
    status TEXT NOT NULL,
    profile_data TEXT,
    created_at TEXT NOT NULL
);
"""

# New table: profile_runs
_CREATE_PROFILE_RUNS: str = """
CREATE TABLE IF NOT EXISTS profile_runs (
    profile_run_id TEXT PRIMARY KEY,
    discovery_run_id TEXT,
    start_profiling_at TEXT,
    end_profiling_at TEXT,
    status TEXT NOT NULL,
    error_summary TEXT,
    repository_count INTEGER NOT NULL DEFAULT 1
);
"""

# Indexes for fast lookup of profiles / runs by discovery run
_CREATE_REPOSITORY_PROFILES_DISCOVERY_RUN_ID_INDEX: str = """
CREATE INDEX IF NOT EXISTS idx_repository_profiles_discovery_run_id
    ON repository_profiles (discovery_run_id);
"""

_CREATE_PROFILE_RUNS_DISCOVERY_RUN_ID_INDEX: str = """
CREATE INDEX IF NOT EXISTS idx_profile_runs_discovery_run_id
    ON profile_runs (discovery_run_id);
"""

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class DatabaseError(Exception):
    """Raised for database-level failures (connection, migration, etc.)."""
    pass


class SchemaMismatchError(DatabaseError):
    """Raised when an existing database has an unsupported schema version."""
    pass


# ---------------------------------------------------------------------------
# Connection + lifecycle
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Database:
    """Handle to a connected HBH SQLite database."""
    path: str
    connection: sqlite3.Connection

    @classmethod
    def create(cls, config: Config) -> Database:
        db = sqlite3.connect(config.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        return cls(path=config.db_path, connection=db)

    @classmethod
    def connect(cls, path: str) -> Database:
        db = sqlite3.connect(path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        return cls(path=path, connection=db)

    def close(self) -> None:
        self.connection.close()


@contextmanager
def db_connection(config: Config):
    """
    Context manager yielding a Database handle.

    Usage:
        with db_connection(config) as db:
            db.connection.execute(...)
    """
    db = Database.create(config)
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Schema management
# ---------------------------------------------------------------------------

def ensure_schema(db: Database) -> None:
    """
    Create all v1 tables if missing, run v1→v2→v3 migrations if needed,
    and record schema version.

    Idempotent: safe to call on an already-initialized database.
    """
    with db.connection:
        db.connection.executescript(_CREATE_TABLES)
        version = current_schema_version(db)
        if version == 0:
            # New database — create v1 schema, then migrate to v3
            _ensure_schema_version(db.connection, 1)
            _migrate_v1_to_v2(db.connection)
            _migrate_v2_to_v3(db.connection)
            _ensure_schema_version(db.connection, SCHEMA_VERSION)
        elif 0 < version < SCHEMA_VERSION:
            # Existing database at older version — migrate up
            if version == 1:
                _migrate_v1_to_v2(db.connection)
            elif version == 2:
                _migrate_v2_to_v3(db.connection)
            _ensure_schema_version(db.connection, SCHEMA_VERSION)
        # If version >= SCHEMA_VERSION, nothing to do


def current_schema_version(db: Database) -> int:
    """Read the recorded schema version from the database.

    Returns 0 if the schema_versions table does not exist (uninitialized DB).
    """
    try:
        row = db.connection.execute(
            "SELECT version FROM schema_versions ORDER BY version DESC LIMIT 1"
        ).fetchone()
    except sqlite3.OperationalError:
        return 0
    if row is None:
        return 0
    return int(row["version"])


def validate_schema_version(db: Database) -> None:
    """
    FAIL CLOSED: if the existing database schema version is not supported,
    raise SchemaMismatchError. Never silently overwrite.
    """
    version = current_schema_version(db)
    if version == 0:
        # Not initialized yet — caller should call ensure_schema().
        return
    if version not in _SUPPORTED_SCHEMA_VERSIONS:
        raise SchemaMismatchError(
            f"Database schema version {version} is not supported. "
            f"Supported versions: {sorted(_SUPPORTED_SCHEMA_VERSIONS)}. "
            f"Manual migration required."
        )


def is_initialized(db: Database) -> bool:
    """Return True if the database has been initialized (schema version recorded)."""
    return current_schema_version(db) > 0


# ---------------------------------------------------------------------------
# Migration v1 → v2 (additive, idempotent, data-preserving)
# ---------------------------------------------------------------------------

def _migrate_v2_to_v3(conn: sqlite3.Connection) -> None:
    """
    Apply v2 → v3 migration: add repository_profiles and profile_runs tables,
    and create their indexes. Additive only; no existing data touched.
    """
    conn.execute(_CREATE_REPOSITORY_PROFILES)
    conn.execute(_CREATE_PROFILE_RUNS)
    conn.execute(_CREATE_REPOSITORY_PROFILES_DISCOVERY_RUN_ID_INDEX)
    conn.execute(_CREATE_PROFILE_RUNS_DISCOVERY_RUN_ID_INDEX)


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """
    Apply v1 → v2 migration: add discovery columns to bounties,
    create discovery_runs table, create indexes.

    Idempotent: safe to run multiple times. Uses try/except per column
    to handle already-existing columns gracefully.
    """
    # Add discovery columns to bounties (if not already present)
    for column_def in _BOUNTIES_DISCOVERY_COLUMNS:
        try:
            conn.execute(f"ALTER TABLE bounties ADD COLUMN {column_def}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                continue  # Column already exists — skip
            raise

    # Create discovery_runs table
    conn.execute(_CREATE_DISCOVERY_RUNS)

    # Create indexes
    conn.execute(_CREATE_BOUNTIES_SOURCE_ID_INDEX)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_schema_version(conn: sqlite3.Connection, version: int) -> None:
    """Record or refresh the schema version, idempotent."""
    conn.execute(
        "INSERT OR REPLACE INTO schema_versions (version, applied_at) VALUES (?, ?)",
        (version, _now_iso()),
    )


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# CRUD helpers (Phase 0: minimal; Phase 1b: discovery extension)
# ---------------------------------------------------------------------------

def insert_bounty(db: Database, **fields: Any) -> None:
    if "status" not in fields:
        fields["status"] = "unknown"
    columns = ", ".join(fields.keys())
    placeholders = ", ".join("?" for _ in fields)
    values = tuple(fields.values())
    db.connection.execute(
        f"INSERT OR REPLACE INTO bounties ({columns}) VALUES ({placeholders})",
        values,
    )
    db.connection.commit()


def insert_event(
    db: Database,
    *,
    entity_id: str,
    actor: str,
    reason: str | None = None,
    from_state: str | None = None,
    to_state: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> int:
    row = db.connection.execute(
        """INSERT INTO events (entity_id, from_state, to_state, actor, reason, timestamp, metadata)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            entity_id,
            from_state,
            to_state,
            actor,
            reason,
            _now_iso(),
            None if metadata is None else _serialize_metadata(metadata),
        ),
    )
    db.connection.commit()
    return int(row.lastrowid)


def _serialize_metadata(metadata: dict[str, Any]) -> str:
    import json

    return json.dumps(metadata, default=str)


def count_bounties(db: Database) -> int:
    row = db.connection.execute("SELECT COUNT(*) AS c FROM bounties").fetchone()
    return int(row["c"])


# ---------------------------------------------------------------------------
# Discovery CRUD helpers (Phase 1b-GH-1)
# ---------------------------------------------------------------------------

def insert_discovery_run(
    db: Database,
    *,
    run_id: str,
    started_at: str,
    trigger: str | None = None,
) -> None:
    """
    Insert a new discovery run record with RUNNING status.

    The finished_at, status (beyond RUNNING), and counts are updated
    by the Discovery Engine when the run completes.
    """
    db.connection.execute(
        """INSERT INTO discovery_runs
           (run_id, started_at, trigger, status, adapters_total,
            adapters_succeeded, adapters_failed,
            candidates_found, candidates_inserted, candidates_duplicate,
            error_summary)
           VALUES (?, ?, ?, 'RUNNING', 0, 0, 0, 0, 0, 0, NULL)""",
        (run_id, started_at, trigger),
    )
    db.connection.commit()


def update_discovery_run(
    db: Database,
    *,
    run_id: str,
    finished_at: str,
    status: str,
    adapters_total: int,
    adapters_succeeded: int,
    adapters_failed: int,
    candidates_found: int,
    candidates_inserted: int,
    candidates_duplicate: int,
    error_summary: str | None = None,
) -> None:
    """
    Update a discovery run with completion data.

    Called by the Discovery Engine when all adapters have finished.
    """
    db.connection.execute(
        """UPDATE discovery_runs SET
           finished_at = ?,
           status = ?,
           adapters_total = ?,
           adapters_succeeded = ?,
           adapters_failed = ?,
           candidates_found = ?,
           candidates_inserted = ?,
           candidates_duplicate = ?,
           error_summary = ?
           WHERE run_id = ?""",
        (
            finished_at,
            status,
            adapters_total,
            adapters_succeeded,
            adapters_failed,
            candidates_found,
            candidates_inserted,
            candidates_duplicate,
            error_summary,
            run_id,
        ),
    )
    db.connection.commit()


def get_discovery_run(db: Database, run_id: str) -> dict[str, Any] | None:
    """
    Retrieve a discovery run by run_id.

    Returns None if not found.
    """
    row = db.connection.execute(
        "SELECT * FROM discovery_runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def list_discovery_runs(
    db: Database, limit: int = 10, offset: int = 0
) -> list[dict[str, Any]]:
    """
    List discovery runs, most recent first.

    Args:
        limit: Maximum number of runs to return.
        offset: Number of runs to skip.

    Returns:
        List of run dicts, ordered by started_at DESC.
    """
    rows = db.connection.execute(
        "SELECT * FROM discovery_runs ORDER BY started_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return [dict(row) for row in rows]


def count_discovery_runs(db: Database) -> int:
    """Return the total number of discovery runs recorded."""
    row = db.connection.execute(
        "SELECT COUNT(*) AS c FROM discovery_runs"
    ).fetchone()
    return int(row["c"])


def insert_discovered_bounty(
    db: Database,
    *,
    id: str,
    source: str,
    source_id: str,
    canonical_issue_key: str | None = None,
    title: str | None = None,
    description: str | None = None,
    repository_url: str | None = None,
    issue_url: str | None = None,
    reward: str | None = None,
    currency: str | None = None,
    source_created_at: str | None = None,
    source_updated_at: str | None = None,
    last_activity: str | None = None,
    state: str | None = None,
    labels: str | None = None,  # JSON-encoded list of label strings
    raw_payload_reference: str | None = None,
    raw_payload_hash: str | None = None,
    adapter_version: str | None = None,
    discovery_run_id: str | None = None,
    discovered_at: str | None = None,
    status: str = "discovered",
) -> None:
    """
    Insert a discovered bounty candidate into the bounties table.

    This is the Phase 1b discovery-aware insert. It stores all discovery
    fields alongside the core bounty fields.

    Uses INSERT OR REPLACE to handle re-discovery of the same candidate.
    The (source, source_id) pair should be unique per source; the caller
    is responsible for enforcing uniqueness semantics.

    Args:
        id: Primary key for the bounty record.
        source: Source identifier (e.g. 'github').
        source_id: Primary identity within the source.
        labels: JSON-encoded list of label strings (e.g. '["bug", "good first issue"]').
        status: Bounty status — defaults to 'discovered'.
        discovered_at: When the bounty was discovered — defaults to now.
    """
    if discovered_at is None:
        discovered_at = _now_iso()

    db.connection.execute(
        """INSERT OR REPLACE INTO bounties (
           id, platform, url, title, description, reward,
           created_at, discovered_at, status,
           source, source_id, canonical_issue_key,
           repository_url, issue_url, currency,
           source_created_at, source_updated_at, last_activity,
           state, labels, raw_payload_reference,
           raw_payload_hash, adapter_version, discovery_run_id
         ) VALUES (
           ?, ?, ?, ?, ?, ?,
           ?, ?, ?,
           ?, ?, ?,
           ?, ?, ?,
           ?, ?, ?, ?,
           ?, ?, ?, ?, ?
         )""",
        (
            id,
            source,  # platform maps to source for discovery bounties
            issue_url or "",  # url maps to issue_url for discovery bounties
            title or "",
            description,
            reward,
            source_created_at,  # created_at maps to source_created_at
            discovered_at,
            status,
            source,
            source_id,
            canonical_issue_key,
            repository_url,
            issue_url,
            currency,
            source_created_at,
            source_updated_at,
            last_activity,
            state,
            labels,
            raw_payload_reference,
            raw_payload_hash,
            adapter_version,
            discovery_run_id,
        ),
    )
    db.connection.commit()


def get_discovered_bounties_by_run(
    db: Database, discovery_run_id: str
) -> list[dict[str, Any]]:
    """
    Retrieve all bounties discovered during a specific run.

    Returns bounties where discovery_run_id matches.
    """
    rows = db.connection.execute(
        "SELECT * FROM bounties WHERE discovery_run_id = ?",
        (discovery_run_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def exists_source_source_id(
    db: Database, source: str, source_id: str
) -> bool:
    """
    Check whether a (source, source_id) pair already exists in bounties.

    Used for dedup checks before inserting discovered candidates.
    """
    row = db.connection.execute(
        "SELECT 1 FROM bounties WHERE source = ? AND source_id = ?",
        (source, source_id),
    ).fetchone()
    return row is not None
