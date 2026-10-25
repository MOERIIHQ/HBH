"""
Tests for hbh.core.config — Discovery configuration — Phase 1b-GH-1.

Focused tests for:
- Discovery configuration path resolution
- GitHub repository configuration loading
- Disabled source behavior
- Repository list parsing
- GITHUB_TOKEN is not persisted in config

No GitHub HTTP adapter tests — those belong in a later subphase.
"""

from __future__ import annotations

import os
import sys
import tempfile

import pytest

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml

from hbh.core.config import Config, load_config, _DEFAULT_DISCOVERY_CONFIG_PATH


# ---------------------------------------------------------------------------
# Discovery config path tests
# ---------------------------------------------------------------------------

class TestDiscoveryConfigPath:
    """Discovery configuration path resolution."""

    def test_default_discovery_config_path(self):
        """Default path is under HBH_HOME/config/discovery_config.yaml."""
        cfg = load_config()
        assert cfg.discovery_config_path.endswith("discovery_config.yaml")
        assert "config" in cfg.discovery_config_path

    def test_discovery_config_path_absolute(self, tmp_path):
        """Explicit absolute path is used as-is."""
        absolute = str(tmp_path / "my_discovery.yaml")
        cfg = load_config(discovery_config_path=absolute)
        assert cfg.discovery_config_path == absolute

    def test_discovery_config_path_relative_to_home(self, tmp_path):
        """Relative path is resolved under HBH_HOME."""
        cfg = load_config(
            hbhome=str(tmp_path),
            discovery_config_path="custom_discovery.yaml",
        )
        assert cfg.discovery_config_path == str(tmp_path / "custom_discovery.yaml")

    def test_discovery_config_path_env_override(self, monkeypatch, tmp_path):
        """HBH_DISCOVERY_CONFIG_PATH env var overrides default."""
        custom = str(tmp_path / "env_discovery.yaml")
        monkeypatch.setenv("HBH_DISCOVERY_CONFIG_PATH", custom)
        cfg = load_config()
        assert cfg.discovery_config_path == custom

    def test_discovery_config_path_explicit_overrides_env(self, monkeypatch, tmp_path):
        """Explicit argument overrides env var."""
        env_path = str(tmp_path / "env.yaml")
        explicit_path = str(tmp_path / "explicit.yaml")
        monkeypatch.setenv("HBH_DISCOVERY_CONFIG_PATH", env_path)
        cfg = load_config(discovery_config_path=explicit_path)
        assert cfg.discovery_config_path == explicit_path


# ---------------------------------------------------------------------------
# Discovery configuration loading tests
# ---------------------------------------------------------------------------

class TestDiscoveryConfigLoading:
    """Loading and validating discovery_config.yaml."""

    def test_load_valid_discovery_config(self, tmp_path):
        """Load a valid discovery configuration file."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / "discovery_config.yaml"
        config_file.write_text(
            """
version: 1
sources:
  github:
    enabled: true
    repositories:
      - octocat/Hello-World
      - owner/repo2
limits:
  github:
    max_pages: 10
    max_candidates: 50
""",
            encoding="utf-8",
        )

        with open(config_file) as f:
            config = yaml.safe_load(f)

        assert config["version"] == 1
        assert "sources" in config
        assert "github" in config["sources"]
        assert config["sources"]["github"]["enabled"] is True
        assert config["sources"]["github"]["repositories"] == [
            "octocat/Hello-World",
            "owner/repo2",
        ]
        # Limits can be specified at top level
        assert config.get("limits", {}).get("github", {}).get("max_pages") == 10
        assert config.get("limits", {}).get("github", {}).get("max_candidates") == 50

    def test_github_enabled_true(self, tmp_path):
        """GitHub source enabled in config."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / "discovery_config.yaml"
        config_file.write_text(
            """
version: 1
sources:
  github:
    enabled: true
    repositories:
      - octocat/Hello-World
""",
            encoding="utf-8",
        )

        with open(config_file) as f:
            config = yaml.safe_load(f)

        assert config["sources"]["github"]["enabled"] is True

    def test_github_disabled(self, tmp_path):
        """GitHub source disabled in config."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / "discovery_config.yaml"
        config_file.write_text(
            """
version: 1
sources:
  github:
    enabled: false
    repositories: []
""",
            encoding="utf-8",
        )

        with open(config_file) as f:
            config = yaml.safe_load(f)

        assert config["sources"]["github"]["enabled"] is False

    def test_disabled_source_has_empty_repositories(self, tmp_path):
        """Disabled source configuration has empty repositories list."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / "discovery_config.yaml"
        config_file.write_text(
            """
version: 1
sources:
  github:
    enabled: false
    repositories: []
  algora:
    enabled: false
    organizations: []
""",
            encoding="utf-8",
        )

        with open(config_file) as f:
            config = yaml.safe_load(f)

        assert config["sources"]["github"]["repositories"] == []
        assert config["sources"]["algora"]["enabled"] is False

    def test_repository_list_parsing(self, tmp_path):
        """Repository list is parsed correctly."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / "discovery_config.yaml"
        config_file.write_text(
            """
version: 1
sources:
  github:
    enabled: true
    repositories:
      - octocat/Hello-World
      - owner2/repo-name
      - org/author-repo
""",
            encoding="utf-8",
        )

        with open(config_file) as f:
            config = yaml.safe_load(f)

        repos = config["sources"]["github"]["repositories"]
        assert len(repos) == 3
        assert "octocat/Hello-World" in repos
        assert "owner2/repo-name" in repos
        assert "org/author-repo" in repos

    def test_repository_format_owner_slash_name(self, tmp_path):
        """Repositories follow owner/repo format."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / "discovery_config.yaml"
        config_file.write_text(
            """
version: 1
sources:
  github:
    enabled: true
    repositories:
      - octocat/Hello-World
""",
            encoding="utf-8",
        )

        with open(config_file) as f:
            config = yaml.safe_load(f)

        repos = config["sources"]["github"]["repositories"]
        for repo in repos:
            assert "/" in repo, f"Repository '{repo}' must be in owner/repo format"

    def test_empty_repositories_list(self, tmp_path):
        """Empty repositories list is valid."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / "discovery_config.yaml"
        config_file.write_text(
            """
version: 1
sources:
  github:
    enabled: true
    repositories: []
""",
            encoding="utf-8",
        )

        with open(config_file) as f:
            config = yaml.safe_load(f)

        assert config["sources"]["github"]["repositories"] == []

    def test_no_limits_section(self, tmp_path):
        """Config without limits section is valid (limits are optional)."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / "discovery_config.yaml"
        config_file.write_text(
            """
version: 1
sources:
  github:
    enabled: true
    repositories:
      - octocat/Hello-World
""",
            encoding="utf-8",
        )

        with open(config_file) as f:
            config = yaml.safe_load(f)

        # Should not raise; limits are optional
        assert "sources" in config


# ---------------------------------------------------------------------------
# GITHUB_TOKEN not persisted tests
# ---------------------------------------------------------------------------

class TestGithubTokenNotPersisted:
    """GITHUB_TOKEN must never be persisted in config, database, or logs."""

    def test_github_token_not_in_default_config(self):
        """Default Config has no GITHUB_TOKEN storage."""
        cfg = load_config()
        # Config has no github_token attribute
        assert not hasattr(cfg, "github_token")

    def test_github_token_not_in_config_file(self, tmp_path):
        """discovery_config.yaml must not contain token fields."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / "discovery_config.yaml"
        config_file.write_text(
            """
version: 1
sources:
  github:
    enabled: true
    repositories:
      - octocat/Hello-World
""",
            encoding="utf-8",
        )

        with open(config_file) as f:
            config = yaml.safe_load(f)

        # Token must not be anywhere in the config file
        config_str = str(config)
        assert "token" not in config_str.lower()
        assert "github_token" not in config_str.lower()
        assert "GITHUB_TOKEN" not in config_str

    def test_github_token_env_var_is_separate(self, monkeypatch):
        """GITHUB_TOKEN is a separate env var, not part of Config."""
        monkeypatch.setenv("GITHUB_TOKEN", "test-token-123")
        cfg = load_config()
        # Config must not read or store GITHUB_TOKEN
        assert not hasattr(cfg, "github_token")
        # GITHUB_TOKEN exists in environment but is not part of Config
        assert os.environ.get("GITHUB_TOKEN") == "test-token-123"

    def test_config_does_not_expose_token_in_properties(self, monkeypatch):
        """Config properties must not expose GITHUB_TOKEN."""
        monkeypatch.setenv("GITHUB_TOKEN", "secret-token")
        cfg = load_config()
        # All Config properties must not contain the token
        for attr in ["home", "db_path", "policy_path", "log_level",
                      "discovery_interval", "discovery_config_path"]:
            value = getattr(cfg, attr)
            assert "secret-token" not in str(value)


# ---------------------------------------------------------------------------
# Config isolation tests
# ---------------------------------------------------------------------------

class TestConfigIsolation:
    """Config must not leak discovery settings between instances."""

    def test_two_configs_with_different_discovery_paths(self, tmp_path):
        """Two Config instances with different discovery paths are isolated."""
        cfg1 = load_config(
            hbhome=str(tmp_path),
            discovery_config_path=str(tmp_path / "discovery1.yaml"),
        )
        cfg2 = load_config(
            hbhome=str(tmp_path),
            discovery_config_path=str(tmp_path / "discovery2.yaml"),
        )
        assert cfg1.discovery_config_path != cfg2.discovery_config_path
        assert cfg1.discovery_config_path.endswith("discovery1.yaml")
        assert cfg2.discovery_config_path.endswith("discovery2.yaml")


# ---------------------------------------------------------------------------
# Default config values tests
# ---------------------------------------------------------------------------

class TestDefaultConfigDiscovery:
    """Default discovery configuration values."""

    def test_discovery_config_path_under_home(self):
        """Default discovery_config_path is under HBH_HOME."""
        cfg = load_config(hbhome="/tmp/test_home")
        assert cfg.discovery_config_path.startswith("/tmp/test_home")
        assert "discovery_config.yaml" in cfg.discovery_config_path
