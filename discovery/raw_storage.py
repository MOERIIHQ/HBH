"""
HBH Raw Evidence Storage — Phase 1b-GH-2B.

Content-addressed raw payload storage with SHA-256 integrity verification.

Immutable evidence artifacts stored under:

    <raw_root>/<source>/<sha256>.json

SQLite holds the reference and hash; the filesystem holds the evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SOURCE_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.-]*$")
_MAX_SOURCE_LENGTH = 128


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class RawStorageError(Exception):
    """Base exception for raw storage failures."""


class EvidenceIntegrityError(RawStorageError):
    """Existing evidence file content does not match its hash."""


class UnsafeSourceError(RawStorageError):
    """Source identifier failed path safety validation."""


# ---------------------------------------------------------------------------
# RawStorage
# ---------------------------------------------------------------------------

class RawStorage:
    """
    Content-addressed raw evidence storage.

    Paths: <root>/<source>/<sha256 hex>.json

    - Payloads are canonicalized as UTF-8 JSON with sorted keys.
    - SHA-256 of those bytes becomes the filename AND the stored hash.
    - Duplicate content is deduplicated (same hash → same file, no rewrite).
    - Existing files whose content does not match their hash raise
      EvidenceIntegrityError (never silently overwritten).
    """

    def __init__(self, root: str) -> None:
        self._root = os.path.abspath(root)
        os.makedirs(self._root, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store(self, source: str, payload: dict[str, Any]) -> tuple[str, str]:
        """
        Store *payload* as a content-addressed evidence file.

        Args:
            source: Source namespace (e.g. ``"github"``). Must pass path safety.
            payload: JSON-serializable dict representing the raw evidence.

        Returns:
            ``(relative_path, sha256_hex)`` where *relative_path* is
            ``<source>/<hash>.json`` relative to the storage root.

        Raises:
            UnsafeSourceError: *source* fails path safety validation.
            EvidenceIntegrityError: file already exists with different content.
            RawStorageError: filesystem write failure.
        """
        self._validate_source(source)
        raw_bytes = self._canonicalize(payload)
        content_hash = hashlib.sha256(raw_bytes).hexdigest()
        rel_path = f"{source}/{content_hash}.json"
        full_path = os.path.join(self._root, rel_path)

        if os.path.exists(full_path):
            existing = self._read_bytes(full_path)
            if hashlib.sha256(existing).hexdigest() != content_hash:
                raise EvidenceIntegrityError(
                    f"Evidence file exists with mismatched content: {rel_path}"
                )
            # Duplicate content — same file, no rewrite needed.
            return rel_path, content_hash

        # Write atomically: write to temp, then replace.
        try:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            tmp_path = full_path + ".tmp"
            with open(tmp_path, "wb") as fh:
                fh.write(raw_bytes)
            os.replace(tmp_path, full_path)
        except OSError as exc:
            raise RawStorageError(
                f"Failed to write evidence file {rel_path}: {exc}"
            ) from exc

        return rel_path, content_hash

    def verify(self, relative_path: str, expected_hash: str) -> bool:
        """
        Verify that the evidence file at *relative_path* has *expected_hash*.

        Args:
            relative_path: Path relative to storage root (e.g. ``"github/abc123.json"``).
            expected_hash: Expected SHA-256 hex digest.

        Returns:
            ``True`` if the file exists and its SHA-256 matches.
            ``False`` if the file is missing, unreadable, or hash differs.
        """
        full_path = os.path.normpath(os.path.join(self._root, relative_path))

        # Path traversal guard: resolved path must stay under root.
        if not full_path.startswith(self._root + os.sep) and full_path != self._root:
            return False

        if not os.path.isfile(full_path):
            return False

        try:
            actual = hashlib.sha256(self._read_bytes(full_path)).hexdigest()
            return actual == expected_hash
        except OSError:
            return False

    @property
    def root(self) -> str:
        """Absolute path to the storage root directory."""
        return self._root

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_source(source: str) -> None:
        if not isinstance(source, str) or not source:
            raise UnsafeSourceError("source must be a non-empty string")
        if len(source) > _MAX_SOURCE_LENGTH:
            raise UnsafeSourceError(
                f"source exceeds max length ({_MAX_SOURCE_LENGTH})"
            )
        if "../" in source or ".." in source:
            raise UnsafeSourceError("source contains path traversal sequence")
        if source.startswith("/") or source.startswith("\\"):
            raise UnsafeSourceError("source must not start with path separator")
        if "~" in source:
            raise UnsafeSourceError("source must not contain tilde")
        if not _SOURCE_NAME_RE.match(source):
            raise UnsafeSourceError(
                f"source contains invalid characters: {source!r}"
            )

    @staticmethod
    def _canonicalize(payload: dict[str, Any]) -> bytes:
        """Deterministically serialize *payload* to UTF-8 JSON bytes.

        Requires the payload to be fully JSON-serializable. Non-serializable
        objects raise TypeError — there is no silent fallback conversion.
        """
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    @staticmethod
    def _read_bytes(path: str) -> bytes:
        with open(path, "rb") as fh:
            return fh.read()
