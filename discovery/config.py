"""
HBH Discovery Configuration Loader — Phase 1b-GH-1.

Loads and validates the discovery_config.yaml file.

This is technical runtime configuration for discovery sources.
It is NOT policy rules (those remain in default_policy.yaml).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from hbh.core.config import Config
from hbh.core.audit import log_error, log_info


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class SourceConfig:
    """
    Configuration for a single discovery source.

    Attributes:
        source: Source identifier (e.g. 'github', 'algora').
        enabled: Whether this source is enabled for discovery.
        config: Source-specific configuration dictionary.
    """

    def __init__(
        self,
        source: str,
        enabled: bool,
        config: dict[str, Any] | None = None,
    ) -> None:
        self.source = source
        self.enabled = enabled
        self.config = config or {}

    @property
    def repositories(self) -> list[str]:
        """Return list of repositories for GitHub source."""
        if self.source != "github":
            return []
        return self.config.get("repositories", [])

    @property
    def organizations(self) -> list[str]:
        """Return list of organizations for Algora source."""
        if self.source != "algora":
            return []
        return self.config.get("organizations", [])

    @property
    def max_pages(self) -> int:
        """Max pages for this source (adapter-level limit)."""
        return int(self.config.get("max_pages", 10))

    @property
    def max_candidates(self) -> int:
        """Max candidates for this source (adapter-level limit)."""
        return int(self.config.get("max_candidates", 50))


# ---------------------------------------------------------------------------
# DiscoveryConfig
# ---------------------------------------------------------------------------

class DiscoveryConfig:
    """
    Loaded discovery configuration.

    Contains source configurations and global limits.
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._sources: dict[str, SourceConfig] = {}
        self._loaded = False

    def load(self) -> None:
        """Load discovery configuration from the configured path."""
        if self._loaded:
            return

        config_path = Path(self._config.discovery_config_path)

        if not config_path.is_file():
            log_info(
                event="discovery_config_not_found",
                message=f"Discovery config file not found: {config_path}",
            )
            self._loaded = True
            return

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f)
        except yaml.YAMLError as e:
            log_error(
                event="discovery_config_invalid_yaml",
                message=f"Invalid YAML in discovery config: {e}",
            )
            self._loaded = True
            return

        if not isinstance(raw, dict):
            log_error(
                event="discovery_config_not_mapping",
                message="Discovery config must be a YAML mapping",
            )
            self._loaded = True
            return

        self._parse(raw)
        self._loaded = True

    def _parse(self, raw: dict[str, Any]) -> None:
        """Parse raw YAML into source configurations."""
        sources_raw = raw.get("sources", {})
        if not isinstance(sources_raw, dict):
            return

        for source_name, source_data in sources_raw.items():
            if not isinstance(source_data, dict):
                continue

            enabled = source_data.get("enabled", False)
            self._sources[source_name] = SourceConfig(
                source=source_name,
                enabled=enabled,
                config=source_data,
            )

    # -- accessors --------------------------------------------------------

    @property
    def sources(self) -> dict[str, SourceConfig]:
        """Return all source configurations."""
        return dict(self._sources)

    def get_source(self, source: str) -> SourceConfig | None:
        """Get configuration for a specific source."""
        return self._sources.get(source)

    @property
    def github_enabled(self) -> bool:
        """Whether GitHub discovery is enabled."""
        gh = self._sources.get("github")
        return gh.enabled if gh else False

    @property
    def github_repositories(self) -> list[str]:
        """List of GitHub repositories to discover."""
        gh = self._sources.get("github")
        if gh and gh.enabled:
            return gh.repositories
        return []

    @property
    def github_max_pages(self) -> int:
        """Max pages for GitHub adapter."""
        gh = self._sources.get("github")
        if gh:
            return gh.max_pages
        return 10

    @property
    def github_max_candidates(self) -> int:
        """Max candidates for GitHub adapter."""
        gh = self._sources.get("github")
        if gh:
            return gh.max_candidates
        return 50


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def load_discovery_config(config: Config) -> DiscoveryConfig:
    """
    Load discovery configuration using the given Config.

    Args:
        config: HBH Config instance.

    Returns:
        DiscoveryConfig with loaded source configurations.
    """
    dc = DiscoveryConfig(config)
    dc.load()
    return dc
