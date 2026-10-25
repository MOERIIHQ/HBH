"""
HBH Configuration — Phase 0 + Discovery extension.

Phase 0: configuration layer with environment override.
Phase 1b-GH-1: discovery configuration for source scope and limits.

All values are read once at startup; engines must not hard-code config.
"""

from __future__ import annotations

import os
import sys
from typing import Final

# ---------------------------------------------------------------------------
# Default values (Phase 0 constants)
# ---------------------------------------------------------------------------

_DEFAULT_HBH_HOME: Final[str] = os.path.expanduser("~/.hbh")
_DEFAULT_DB_PATH: Final[str] = "hbh.db"
_DEFAULT_POLICY_PATH: Final[str] = os.path.join("config", "default_policy.yaml")
_DEFAULT_LOG_LEVEL: Final[str] = "INFO"
_DEFAULT_DISCOVERY_INTERVAL: Final[int] = 1800  # 30 minutes

# ---------------------------------------------------------------------------
# Discovery defaults (Phase 1b-GH-1)
# ---------------------------------------------------------------------------

_DEFAULT_DISCOVERY_CONFIG_PATH: Final[str] = os.path.join(
    "config", "discovery_config.yaml"
)

# Phase 1b-GH-2B: raw evidence storage path
_DEFAULT_RAW_STORAGE_PATH: Final[str] = "raw"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class Config:
    """
    Immutable configuration snapshot.

    Loaded once. All engines read from this object; nothing hard-codes
    file paths, intervals, or thresholds.

    Phase 0 fields: home, db_path, policy_path, log_level, discovery_interval.
    Phase 1b-GH-1 fields: discovery_config_path.
    """

    def __init__(
        self,
        hbhome: str | None = None,
        db_path: str | None = None,
        policy_path: str | None = None,
        log_level: str | None = None,
        discovery_interval: int | None = None,
        discovery_config_path: str | None = None,
        raw_storage_path: str | None = None,
    ) -> None:
        resolved_home = hbhome or os.environ.get("HBH_HOME", _DEFAULT_HBH_HOME)

        self._home = os.path.abspath(resolved_home)

        resolved_db = db_path or os.environ.get("HBH_DB_PATH", _DEFAULT_DB_PATH)
        self._db_path = _as_absolute_under_home(resolved_db, self._home)

        resolved_policy = policy_path or os.environ.get(
            "HBH_POLICY_PATH", _DEFAULT_POLICY_PATH
        )
        self._policy_path = _as_absolute_under_home(resolved_policy, self._home)

        resolved_log = log_level or os.environ.get("HBH_LOG_LEVEL", _DEFAULT_LOG_LEVEL)
        self._log_level = resolved_log.upper()

        if discovery_interval is not None:
            self._discovery_interval = discovery_interval
        else:
            raw = os.environ.get("HBH_DISCOVERY_INTERVAL")
            self._discovery_interval = (
                _DEFAULT_DISCOVERY_INTERVAL if raw is None else int(raw)
            )

        # Phase 1b-GH-1: discovery configuration path
        if discovery_config_path is not None:
            self._discovery_config_path = _as_absolute_under_home(
                discovery_config_path, self._home
            )
        else:
            raw = os.environ.get("HBH_DISCOVERY_CONFIG_PATH")
            self._discovery_config_path = (
                _as_absolute_under_home(raw, self._home)
                if raw
                else _as_absolute_under_home(_DEFAULT_DISCOVERY_CONFIG_PATH, self._home)
            )

        # Phase 1b-GH-2B: raw evidence storage path
        if raw_storage_path is not None:
            raw = raw_storage_path
        else:
            raw = os.environ.get("HBH_RAW_STORAGE_PATH")
        if raw:
            self._raw_storage_path = _as_absolute_under_home(raw, self._home)
        else:
            self._raw_storage_path = None

    # -- accessors --------------------------------------------------------

    @property
    def home(self) -> str:
        return self._home

    @property
    def db_path(self) -> str:
        return self._db_path

    @property
    def policy_path(self) -> str:
        return self._policy_path

    @property
    def log_level(self) -> str:
        return self._log_level

    @property
    def discovery_interval(self) -> int:
        return self._discovery_interval

    # -- Phase 1b-GH-1: discovery configuration -------------------------

    @property
    def discovery_config_path(self) -> str:
        """Path to the discovery configuration YAML file."""
        return self._discovery_config_path

    # -- Phase 1b-GH-2B: raw storage ----------------------------------------

    @property
    def raw_storage_path(self) -> str | None:
        """Absolute path to the raw evidence storage root, or None if not configured."""
        return self._raw_storage_path if hasattr(self, "_raw_storage_path") else None

    # -- helpers ----------------------------------------------------------

    def ensure_home(self) -> None:
        """Create HBH_HOME tree if missing. Idempotent."""
        os.makedirs(self._home, exist_ok=True)
        os.makedirs(os.path.join(self._home, "config"), exist_ok=True)


def _as_absolute_under_home(path: str, home: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.join(home, path)


def load_config(
    hbhome: str | None = None,
    db_path: str | None = None,
    policy_path: str | None = None,
    log_level: str | None = None,
    discovery_interval: int | None = None,
    discovery_config_path: str | None = None,
    raw_storage_path: str | None = None,
) -> Config:
    """
    Public entry point for configuration loading.

    Accepts explicit values (for tests) or falls back to env / defaults.
    """
    return Config(
        hbhome=hbhome,
        db_path=db_path,
        policy_path=policy_path,
        log_level=log_level,
        discovery_interval=discovery_interval,
        discovery_config_path=discovery_config_path,
        raw_storage_path=raw_storage_path,
    )
