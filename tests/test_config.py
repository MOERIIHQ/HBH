"""
Tests for hbh.core.config — Phase 0.
"""

import os
import sys
import tempfile

import pytest

from hbh.core.config import Config, load_config, _DEFAULT_DISCOVERY_INTERVAL


class TestDefaultConfig:
    def test_home_defaults_to_dot_hbh(self):
        cfg = load_config()
        assert cfg.home.endswith(".hbh") or ".hbh" in cfg.home

    def test_db_path_under_home(self):
        cfg = load_config()
        assert cfg.db_path.endswith("hbh.db")

    def test_policy_path_under_home(self):
        cfg = load_config()
        assert "default_policy.yaml" in cfg.policy_path

    def test_log_level_default(self):
        cfg = load_config()
        assert cfg.log_level == "INFO"

    def test_discovery_interval_default(self):
        cfg = load_config()
        assert cfg.discovery_interval == _DEFAULT_DISCOVERY_INTERVAL


class TestEnvironmentOverride:
    def test_hbh_home_override(self, monkeypatch):
        with tempfile.TemporaryDirectory() as td:
            monkeypatch.setenv("HBH_HOME", td)
            cfg = load_config()
            assert cfg.home == td

    def test_hbh_db_path_override(self, monkeypatch, tmp_path):
        custom_db = tmp_path / "custom.db"
        monkeypatch.setenv("HBH_DB_PATH", str(custom_db))
        cfg = load_config()
        assert cfg.db_path == str(custom_db)

    def test_hbh_policy_path_override(self, monkeypatch, tmp_path):
        custom_policy = tmp_path / "policy.yaml"
        monkeypatch.setenv("HBH_POLICY_PATH", str(custom_policy))
        cfg = load_config()
        assert cfg.policy_path == str(custom_policy)

    def test_hbh_log_level_override(self, monkeypatch):
        monkeypatch.setenv("HBH_LOG_LEVEL", "DEBUG")
        cfg = load_config()
        assert cfg.log_level == "DEBUG"

    def test_hbh_discovery_interval_override(self, monkeypatch):
        monkeypatch.setenv("HBH_DISCOVERY_INTERVAL", "60")
        cfg = load_config()
        assert cfg.discovery_interval == 60


class TestExplicitArguments:
    def test_explicit_values_take_priority(self):
        cfg = load_config(
            hbhome="/explicit/home",
            db_path="/explicit/db.sqlite",
            policy_path="/explicit/policy.yaml",
            log_level="WARNING",
            discovery_interval=999,
        )
        assert cfg.home == "/explicit/home"
        assert cfg.db_path == "/explicit/db.sqlite"
        assert cfg.policy_path == "/explicit/policy.yaml"
        assert cfg.log_level == "WARNING"
        assert cfg.discovery_interval == 999


class TestEnsureHome:
    def test_creates_home_and_config_tree(self, tmp_path):
        cfg = load_config(hbhome=str(tmp_path / "test_home"))
        cfg.ensure_home()
        assert (tmp_path / "test_home").is_dir()
        assert (tmp_path / "test_home" / "config").is_dir()
