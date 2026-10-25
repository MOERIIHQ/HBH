"""
HBH Repository Profiler Foundation — RP-1.

Deterministic repository identity, RepositoryProfile contract, profile result,
dan profile run context.

Cell satupun tidak melakukan network request, clone, subprocess, eval, exec,
atau persistence. Hanya model dan contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Reuse existing contract version constant from discovery.models.
# Jika future verges berbeda, profile adapter versi sendiri.
ADAPTER_CONTRACT_VERSION: str = "1.0.0"

# ---------------------------------------------------------------------------
# Profile status — mengikuti existing AdapterStatus pattern.
# ---------------------------------------------------------------------------

class ProfileStatus(str):
    """Literal values for profile result status: SUCCESS / PARTIAL / FAILED."""

    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"

    @classmethod
    def is_valid(cls, value: str) -> bool:
        return value in (cls.SUCCESS, cls.PARTIAL, cls.FAILED)

# ---------------------------------------------------------------------------
# Repository identity — deterministic, normalization-only.
# ---------------------------------------------------------------------------

# Valid characters for owner dan repository name sesuai GitHub convention:
# alphanumeric, hyphen, dot, underscore. Tapi spec tidak menspesifikasikan
# karakter yang dilarang selain yang didokumentasikan GitHub, jadi kita
# terima input yang masuk akal dan tolak yang jelas-jelas invalid.
_REPO_ID_PATTERN = re.compile(r"^[a-zA-Z0-9._-]+$")

@dataclass(frozen=True)
class RepositoryIdentity:
    """
    Deterministic repository identity.

    Source-agnostic foundation. GitHub V1 menggunakan source="github".
    """

    source: str
    """Source identifier, mis. 'github'."""

    repository: str
    """Canonical 'owner/repository' setelah normalization."""

    canonical_url: str
    """https://github.com/owner/repository"""

    owner: str
    """Owner yang dinormalisasi."""

    name: str
    """Repository name yang dinormalisasi, tanpa .git suffix."""

    def __post_init__(self) -> None:
        if not self.source:
            raise ValueError("source must not be empty")
        if not self.repository:
            raise ValueError("repository must not be empty")
        if not self.owner:
            raise ValueError("owner must not be empty")
        if not self.name:
            raise ValueError("name must not be empty")
        if "/" not in self.repository:
            raise ValueError(
                f"repository must contain '/': {self.repository!r}"
            )
        # Validasi bahwa repository string adalah owner/name
        parts = self.repository.split("/", 1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise ValueError(
                f"repository must be owner/name: {self.repository!r}"
            )
        if parts[0] != self.owner or parts[1] != self.name:
            raise ValueError(
                f"repository {self.repository!r} inconsistent with "
                f"owner={self.owner!r} name={self.name!r}"
            )
        if not self.canonical_url:
            raise ValueError("canonical_url must not be empty")
        if not self.canonical_url.startswith("https://"):
            raise ValueError(
                f"canonical_url must be https://: {self.canonical_url!r}"
            )

    @property
    def source_id(self) -> str:
        """Bentuk source_id yang konsisten dengan existing convention:
        source:owner/repository untuk keperluan deduplication."""
        return f"{self.source}:{self.repository}"

    def __str__(self) -> str:
        return self.source_id

# ---------------------------------------------------------------------------
# Normalization — deterministic, no network.
# ---------------------------------------------------------------------------

def normalize_repository_identity(
    source: str,
    raw_input: str,
) -> RepositoryIdentity:
    """
    Normalisasi berbagai bentuk input repository menjadi RepositoryIdentity.

    Bentuk yang didukung:
    - owner/repository
    - owner/repository.git
    - owner/repository/           (trailing slash)
    - https://github.com/owner/repo
    - https://github.com/owner/repo.git
    - https://github.com/owner/repo/

    Trailing whitespace dihilangkan.
    Prefix 'github:' dihilangkan jika ada.
    .git suffix dihilangkan (jika ada).
    Trailing slash dihilangkan (jika ada).

    Jika input invalid, raise ValueError secara deterministic.
    Tidak ada network request. Tidak ada DNS resolution.
    """

    if not raw_input or not isinstance(raw_input, str):
        raise ValueError(f"raw_input must be non-empty string: {raw_input!r}")

    value = raw_input.strip()

    # Hilangkan 'github:' prefix jika ada
    if value.startswith("github:"):
        value = value[7:]

    # Jika URL GitHub
    if value.startswith("https://github.com/"):
        value = value[len("https://github.com/"):]

    # Hilangkan trailing slash
    value = value.rstrip("/")

    # Hilangkan .git suffix
    if value.endswith(".git"):
        value = value[:-4]

    # Sekarang value harus owner/repository
    if "/" not in value:
        raise ValueError(
            f"Invalid repository format (no /): {raw_input!r}"
        )

    parts = value.split("/", 1)
    owner, name = parts[0], parts[1]

    if not owner or not name:
        raise ValueError(
            f"Owner and name must not be empty: {raw_input!r}"
        )

    # GitHub owner dan name tidak boleh kosong, tidak boleh mengandung spasi
    if " " in owner or " " in name:
        raise ValueError(
            f"Owner and name must not contain whitespace: {raw_input!r}"
        )

    repository = f"{owner}/{name}"
    canonical_url = f"https://github.com/{owner}/{name}"

    return RepositoryIdentity(
        source=source,
        repository=repository,
        canonical_url=canonical_url,
        owner=owner,
        name=name,
    )

# ---------------------------------------------------------------------------
# RepositoryProfile — logical schema sesuai specification.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RepositoryProfile:
    """
    Hasil profiling repository berisi fakta-fakta verifiable.

    Kategori (sesuai specification RP-SPEC):

    1. Identity (wajib)
    2. Provenance (wajib - moved to second position for dataclass ordering)
    3. Repository State (opsional/nullable)
    4. Metadata (opsional/nullable)
    5. Scale (opsional/nullable)
    6. Language (opsional/nullable)
    7. License (opsional/nullable)
    8. Activity (opsional/nullable)
    """

    # --- 1. IDENTITY (Wajib) ---

    source: str
    """Source identifier, mis. 'github'."""

    repository: str
    """Canonical 'owner/repository'."""

    canonical_url: str
    """https://github.com/owner/repository."""

    owner: str
    """Owner yang dinormalisasi."""

    name: str
    """Repository name yang dinormalisasi, tanpa .git."""

    # --- 2. PROVENANCE (Wajib) - required must come before optional ---

    profile_run_id: str
    """ID unik dari profile run ini."""

    profiled_at: str
    """ISO-8601 timestamp kapan profiling dilakukan."""

    source_endpoint: str
    """Endpoint API yang digunakan, mis. '/repos/{owner}/{repo}'."""

    adapter_version: str
    """Versi adapter profiler, mis. ADAPTER_CONTRACT_VERSION."""

    raw_payload_reference: Optional[str] = None
    """Reference ke raw evidence (diset oleh orchestration layer)."""

    raw_payload_hash: Optional[str] = None
    """Hash dari raw evidence (diset oleh orchestration layer)."""

    # --- 3. REPOSITORY STATE (Opsional/Nullable) ---

    visibility: Optional[str] = None
    """"public" atau "private" jika tersedia dari source."""

    archived: Optional[bool] = None
    """True jika repository archived."""

    fork: Optional[bool] = None
    """True jika repository adalah fork."""

    default_branch: Optional[str] = None
    """Nama default branch, mis. 'main' atau 'master'."""

    # --- 4. METADATA (Opsional/Nullable) ---

    description: Optional[str] = None
    """Deskripsi repository dari source."""

    created_at: Optional[str] = None
    """ISO-8601 timestamp kapan repository dibuat."""

    updated_at: Optional[str] = None
    """ISO-8601 timestamp kapan repository terakhir di-update."""

    pushed_at: Optional[str] = None
    """ISO-8601 timestamp kapan terakhir push."""

    # --- 5. SCALE (Opsional/Nullable) ---

    size_kb: Optional[int] = None
    """Ukuran repository dalam KB."""

    # --- 6. LANGUAGE (Opsional/Nullable) ---

    primary_language: Optional[str] = None
    """Bahasa pemrograman dominan jika tersedia."""

    language_breakdown: Optional[Dict[str, int]] = None
    """Pemetaan bahasa ke kontribusi (persentase/byte)."""

    # --- 7. LICENSE (Opsional/Nullable) ---

    license_detected: Optional[bool] = None
    """True jika license terdeteksi."""

    license_spdx_id: Optional[str] = None
    """SPDX identifier, mis. 'MIT', 'Apache-2.0'."""

    license_name: Optional[str] = None
    """Nama license dari source."""

    # --- 8. ACTIVITY (Opsional/Nullable) ---

    open_issues_count: Optional[int] = None
    """Jumlah open issues."""

    stars: Optional[int] = None
    """Jumlah stars."""

    forks_count: Optional[int] = None
    """Jumlah forks."""

    watchers: Optional[int] = None
    """Jumlah watchers."""

    def __post_init__(self) -> None:
        # Wajib field tidak boleh kosong
        if not self.source:
            raise ValueError("source must not be empty")
        if not self.repository:
            raise ValueError("repository must not be empty")
        if not self.canonical_url:
            raise ValueError("canonical_url must not be empty")
        if not self.owner:
            raise ValueError("owner must not be empty")
        if not self.name:
            raise ValueError("name must not be empty")
        if not self.profile_run_id:
            raise ValueError("profile_run_id must not be empty")
        if not self.profiled_at:
            raise ValueError("profiled_at must not be empty")
        if not self.source_endpoint:
            raise ValueError("source_endpoint must not be empty")
        if not self.adapter_version:
            raise ValueError("adapter_version must not be empty")

        # Validasi tipe field opsional
        if self.visibility is not None and not isinstance(self.visibility, str):
            raise TypeError("visibility must be str or None")
        if self.archived is not None and not isinstance(self.archived, bool):
            raise TypeError("archived must be bool or None")
        if self.fork is not None and not isinstance(self.fork, bool):
            raise TypeError("fork must be bool or None")
        if self.default_branch is not None and not isinstance(self.default_branch, str):
            raise TypeError("default_branch must be str or None")
        if self.description is not None and not isinstance(self.description, str):
            raise TypeError("description must be str or None")
        if self.created_at is not None and not isinstance(self.created_at, str):
            raise TypeError("created_at must be str or None")
        if self.updated_at is not None and not isinstance(self.updated_at, str):
            raise TypeError("updated_at must be str or None")
        if self.pushed_at is not None and not isinstance(self.pushed_at, str):
            raise TypeError("pushed_at must be str or None")
        if self.size_kb is not None and not isinstance(self.size_kb, int):
            raise TypeError("size_kb must be int or None")
        if self.primary_language is not None and not isinstance(self.primary_language, str):
            raise TypeError("primary_language must be str or None")
        if self.language_breakdown is not None and not isinstance(self.language_breakdown, dict):
            raise TypeError("language_breakdown must be dict or None")
        if self.license_detected is not None and not isinstance(self.license_detected, bool):
            raise TypeError("license_detected must be bool or None")
        if self.license_spdx_id is not None and not isinstance(self.license_spdx_id, str):
            raise TypeError("license_spdx_id must be str or None")
        if self.license_name is not None and not isinstance(self.license_name, str):
            raise TypeError("license_name must be str or None")
        if self.open_issues_count is not None and not isinstance(self.open_issues_count, int):
            raise TypeError("open_issues_count must be int or None")
        if self.stars is not None and not isinstance(self.stars, int):
            raise TypeError("stars must be int or None")
        if self.forks_count is not None and not isinstance(self.forks_count, int):
            raise TypeError("forks_count must be int or None")
        if self.watchers is not None and not isinstance(self.watchers, int):
            raise TypeError("watchers must be int or None")
        if self.raw_payload_reference is not None and not isinstance(self.raw_payload_reference, str):
            raise TypeError("raw_payload_reference must be str or None")
        if self.raw_payload_hash is not None and not isinstance(self.raw_payload_hash, str):
            raise TypeError("raw_payload_hash must be str or None")

        # Validasi repository konsisten dengan owner/name
        repo_parts = self.repository.split("/", 1)
        if len(repo_parts) != 2 or repo_parts[0] != self.owner or repo_parts[1] != self.name:
            raise ValueError(
                f"repository {self.repository!r} inconsistent with "
                f"owner={self.owner!r} name={self.name!r}"
            )

        # Validasi canonical_url
        expected_url = f"https://github.com/{self.owner}/{self.name}"
        if self.canonical_url != expected_url:
            raise ValueError(
                f"canonical_url {self.canonical_url!r} does not match "
                f"expected {expected_url!r}"
            )

    @property
    def identity(self) -> RepositoryIdentity:
        """Ekstrak RepositoryIdentity dari profile (untuk penggunaan external)."""
        return RepositoryIdentity(
            source=self.source,
            repository=self.repository,
            canonical_url=self.canonical_url,
            owner=self.owner,
            name=self.name,
        )

    def is_minimum_valid(self) -> bool:
        """
        Apakah profile ini memiliki minimum required metadata untuk SUCCESS.

        Minimum: source, repository, canonical_url, owner, name.
        Semua field wajib sudah ada (di-__post_init__ verifikasi).
        """
        return bool(
            self.source
            and self.repository
            and self.canonical_url
            and self.owner
            and self.name
        )

# ---------------------------------------------------------------------------
# Profile result — wrapper untuk status + profile + metadata.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProfileResult:
    """
    Hasil profiling sebuah repository.

    Contract:
    - FAILED: profile harus None (tidak ada valid profile)
    - PARTIAL: profile minimal valid (identity lengkap), sebagian data missing
    - SUCCESS: profile lengkap dengan semua data yang tersedia
    """

    status: str
    """SUCCESS, PARTIAL, atau FAILED."""

    profile: Optional[RepositoryProfile] = None
    """Profile yang dihasilkan. None jika FAILED."""

    error: Optional[str] = None
    """Human-readable error summary. None jika SUCCESS."""

    rate_limit_hit: bool = False
    """True jika rate limit tercapai selama profiling."""

    elapsed_seconds: float = 0.0
    """Wall-clock waktu profiling dalam detik."""

    def __post_init__(self) -> None:
        if not self.status:
            raise ValueError("status must not be empty")
        if self.status not in (ProfileStatus.SUCCESS, ProfileStatus.PARTIAL, ProfileStatus.FAILED):
            raise ValueError(
                f"status must be one of SUCCESS/PARTIAL/FAILED; got {self.status!r}"
            )
        if self.status == ProfileStatus.FAILED and self.profile is not None:
            raise ValueError(
                "FAILED result must have profile=None"
            )
        if self.status == ProfileStatus.SUCCESS and self.profile is None:
            raise ValueError(
                "SUCCESS result must have a profile"
            )
        if self.status == ProfileStatus.PARTIAL and self.profile is None:
            raise ValueError(
                "PARTIAL result must have a profile (minimum valid)"
            )
        if self.elapsed_seconds < 0:
            raise ValueError("elapsed_seconds must be >= 0")

# ---------------------------------------------------------------------------
# Profile run context — tanpa network, tanpa persistence.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProfileRunContext:
    """
    Context untuk profile run.

    Tidak melakukan network. Tidak melakukan persistence.
    Hanya pembungkus data run.
    """

    profile_run_id: str
    """ID unik untuk run ini."""

    started_at: datetime
    """Timestamp ketika run dimulai."""

    repository: RepositoryIdentity
    """Repository yang akan diprofil."""

    source_config: Dict[str, Any] = field(default_factory=dict)
    """Configuration dict untuk source-specific settings."""

    def __post_init__(self) -> None:
        if not self.profile_run_id:
            raise ValueError("profile_run_id must not be empty")
        if not self.repository:
            raise ValueError("repository must not be empty")

# ---------------------------------------------------------------------------
# Configuration contract — foundational, tidak berlebihan.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RepositoryProfilerConfig:
    """
    Configuration contract untuk Repository Profiler V1.

    Minimal sesuai specification.
    """

    enabled: bool = False
    """Apakah profiler diaktifkan."""

    timeout_seconds: int = 10
    """Timeout per request (konsisten dengan GH-3B default)."""

    max_repositories_per_run: int = 100
    """Maksimum repository yang diprofil per run."""

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be bool")
        if not isinstance(self.timeout_seconds, int) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive int")
        if not isinstance(self.max_repositories_per_run, int) or self.max_repositories_per_run <= 0:
            raise ValueError("max_repositories_per_run must be positive int")

# ---------------------------------------------------------------------------
# Helper constructors untuk testing.
# ---------------------------------------------------------------------------

def make_repository_identity(
    source: str = "github",
    owner: str = "owner",
    name: str = "repo",
) -> RepositoryIdentity:
    """Buat RepositoryIdentity untuk testing."""
    return RepositoryIdentity(
        source=source,
        repository=f"{owner}/{name}",
        canonical_url=f"https://github.com/{owner}/{name}",
        owner=owner,
        name=name,
    )

def make_repository_profile(
    source: str = "github",
    owner: str = "owner",
    name: str = "repo",
    *,
    profile_run_id: str = "run-001",
    profiled_at: Optional[str] = None,
    source_endpoint: str = "/repos/owner/repo",
    adapter_version: str = ADAPTER_CONTRACT_VERSION,
    **kwargs: Any,
) -> RepositoryProfile:
    """Buat RepositoryProfile lengkap untuk testing."""
    now = datetime.now(timezone.utc).isoformat()
    return RepositoryProfile(
        source=source,
        repository=f"{owner}/{name}",
        canonical_url=f"https://github.com/{owner}/{name}",
        owner=owner,
        name=name,
        profile_run_id=profile_run_id,
        profiled_at=profiled_at or now,
        source_endpoint=source_endpoint,
        adapter_version=adapter_version,
        **kwargs,
    )

def make_profile_result(
    status: str = ProfileStatus.SUCCESS,
    *,
    profile: Optional[RepositoryProfile] = None,
    error: Optional[str] = None,
    rate_limit_hit: bool = False,
    elapsed_seconds: float = 0.0,
) -> ProfileResult:
    """Buat ProfileResult untuk testing."""
    return ProfileResult(
        status=status,
        profile=profile,
        error=error,
        rate_limit_hit=rate_limit_hit,
        elapsed_seconds=elapsed_seconds,
    )

# ---------------------------------------------------------------------------
# Profile run context builder.
# ---------------------------------------------------------------------------

def build_profile_run_context(
    profile_run_id: str,
    repository: RepositoryIdentity,
    started_at: Optional[datetime] = None,
    source_config: Optional[Dict[str, Any]] = None,
) -> ProfileRunContext:
    """Buat ProfileRunContext untuk profile run.

    Kontrak:
    - profile_run_id: wajib, string yang tidak kosong.
    - repository: wajib, instance RepositoryIdentity yang valid.
    - started_at: opsional. Jika tidak diberikan, dibuatkan timestamp UTC
      pada saat pemanggilan. Jika diberikan, disimpan apa adanya (naive
      tidak dikonversi ke UTC; perilaku eksplisit, tidak bentrok dengan RP-1).
    - source_config: opsional. None berarti kosong. Bukan dict -> ValueError.
    - Mengembalikan ProfileRunContext yang sudah ada. Tidak mengubah input
      dan tidak menyimpan state global.
    """
    if not isinstance(profile_run_id, str) or not profile_run_id.strip():
        raise ValueError("profile_run_id must be a non-empty string (whitespace not allowed)")

    if not isinstance(repository, RepositoryIdentity):
        raise ValueError(
            "repository must be an instance of RepositoryIdentity"
        )

    if started_at is None:
        started_at = datetime.now(timezone.utc)
    elif not isinstance(started_at, datetime):
        raise ValueError("started_at must be a datetime or None")

    if source_config is None:
        source_config = {}
    elif not isinstance(source_config, dict):
        raise ValueError("source_config must be a dict or None")

    return ProfileRunContext(
        profile_run_id=profile_run_id,
        started_at=started_at,
        repository=repository,
        source_config=source_config,
    )
