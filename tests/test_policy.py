"""
Tests for hbh.core.policy — Phase 0.

Policy tests reconstructed from hbh/core/policy.py contract.
Canonical schema: hard_reject list of single-key mappings.
"""

from __future__ import annotations

import pytest
from pathlib import Path
import tempfile

from hbh.core.policy import (
    load_policy,
    show_policy,
    Policy,
    PolicyError,
    SUPPORTED_POLICY_VERSIONS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_policy(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "policy.yaml"
    p.write_text(text, encoding="utf-8")
    return p


VALID_POLICY_TEXT = """\
version: 1

hard_reject:
  - repo_inaccessible: true
  - license_missing: true
  - estimated_size_kb: "> 500000"

penalties:
  inactive_days:
    threshold: 90
    weight: -15

  existing_pr_count:
    threshold: 3
    weight: -20

human_gate_required:
  - credential_write_required: true
  - touches_auth_code: true
  - touches_crypto_code: true
  - force_push: true
"""


# ---------------------------------------------------------------------------
# Valid policy
# ---------------------------------------------------------------------------

class TestValidPolicy:
    def test_loads_valid_policy(self, tmp_path):
        p = _write_policy(tmp_path, VALID_POLICY_TEXT)
        policy = load_policy(str(p))
        assert isinstance(policy, Policy)
        assert policy.version == 1
        assert len(policy.hard_reject) == 3
        assert policy.hard_reject[0].key == "repo_inaccessible"
        assert policy.hard_reject[0].value is True
        assert policy.hard_reject[1].key == "license_missing"
        assert policy.hard_reject[2].key == "estimated_size_kb"
        assert policy.hard_reject[2].value == "> 500000"
        assert "inactive_days" in policy.penalties
        assert policy.penalties["inactive_days"].threshold == 90
        assert policy.penalties["inactive_days"].weight == -15
        assert "existing_pr_count" in policy.penalties
        assert policy.penalties["existing_pr_count"].threshold == 3
        assert policy.penalties["existing_pr_count"].weight == -20
        assert len(policy.human_gate_required) == 4
        assert policy.human_gate_required[0].key == "credential_write_required"
        assert policy.human_gate_required[0].value is True
        assert policy.human_gate_required[-1].key == "force_push"

    def test_show_policy_output(self, tmp_path):
        p = _write_policy(tmp_path, VALID_POLICY_TEXT)
        policy = load_policy(str(p))
        out = show_policy(policy)
        assert "Policy version: 1" in out
        assert "repo_inaccessible: True" in out
        assert "license_missing: True" in out
        assert "estimated_size_kb: > 500000" in out
        assert "inactive_days:" in out
        assert "threshold: 90" in out
        assert "weight: -15" in out
        assert "existing_pr_count:" in out
        assert "credential_write_required: True" in out
        assert "force_push: True" in out

    def test_policy_object_hard_reject_keys(self, tmp_path):
        p = _write_policy(tmp_path, VALID_POLICY_TEXT)
        policy = load_policy(str(p))
        keys = policy.hard_reject_keys()
        assert "repo_inaccessible" in keys
        assert "license_missing" in keys

    def test_policy_object_human_gate_keys(self, tmp_path):
        p = _write_policy(tmp_path, VALID_POLICY_TEXT)
        policy = load_policy(str(p))
        keys = policy.human_gate_keys()
        assert "credential_write_required" in keys
        assert "force_push" in keys


# ---------------------------------------------------------------------------
# YAML validation
# ---------------------------------------------------------------------------

class TestInvalidYAML:
    def test_malformed_yaml_raises(self, tmp_path):
        p = _write_policy(tmp_path, "{{{broken\n")
        with pytest.raises(PolicyError, match="Invalid YAML"):
            load_policy(str(p))

    def test_yaml_not_mapping_raises(self, tmp_path):
        p = _write_policy(tmp_path, "- item1\n- item2\n")
        with pytest.raises(PolicyError, match="must contain a YAML mapping"):
            load_policy(str(p))


# ---------------------------------------------------------------------------
# Required fields
# ---------------------------------------------------------------------------

class TestMissingRequiredFields:
    def test_missing_version(self, tmp_path):
        p = _write_policy(tmp_path, "hard_reject: []\npenalties: {}\nhuman_gate_required: []\n")
        with pytest.raises(PolicyError, match="missing required field 'version'"):
            load_policy(str(p))

    def test_missing_hard_reject(self, tmp_path):
        p = _write_policy(tmp_path, "version: 1\npenalties: {}\nhuman_gate_required: []\n")
        with pytest.raises(PolicyError, match="missing required field 'hard_reject'"):
            load_policy(str(p))

    def test_missing_penalties(self, tmp_path):
        p = _write_policy(tmp_path, "version: 1\nhard_reject: []\nhuman_gate_required: []\n")
        with pytest.raises(PolicyError, match="missing required field 'penalties'"):
            load_policy(str(p))

    def test_missing_human_gate_required(self, tmp_path):
        p = _write_policy(tmp_path, "version: 1\nhard_reject: []\npenalties: {}\n")
        with pytest.raises(PolicyError, match="missing required field 'human_gate_required'"):
            load_policy(str(p))


# ---------------------------------------------------------------------------
# Version validation
# ---------------------------------------------------------------------------

class TestUnsupportedVersion:
    def test_version_not_int(self, tmp_path):
        p = _write_policy(tmp_path, "version: '1'\nhard_reject: []\npenalties: {}\nhuman_gate_required: []\n")
        with pytest.raises(PolicyError, match="must be an integer"):
            load_policy(str(p))

    def test_version_2_rejected(self, tmp_path):
        p = _write_policy(tmp_path, "version: 2\nhard_reject: []\npenalties: {}\nhuman_gate_required: []\n")
        with pytest.raises(PolicyError, match="not supported"):
            load_policy(str(p))

    def test_version_0_rejected(self, tmp_path):
        p = _write_policy(tmp_path, "version: 0\nhard_reject: []\npenalties: {}\nhuman_gate_required: []\n")
        with pytest.raises(PolicyError, match="not supported"):
            load_policy(str(p))


# ---------------------------------------------------------------------------
# Type validation
# ---------------------------------------------------------------------------

class TestInvalidTypes:
    def test_hard_reject_not_list(self, tmp_path):
        p = _write_policy(tmp_path, "version: 1\nhard_reject: 'not-a-list'\npenalties: {}\nhuman_gate_required: []\n")
        with pytest.raises(PolicyError, match="must be a list"):
            load_policy(str(p))

    def test_penalties_not_mapping(self, tmp_path):
        p = _write_policy(tmp_path, "version: 1\nhard_reject: []\npenalties: 'not-a-map'\nhuman_gate_required: []\n")
        with pytest.raises(PolicyError, match="must be a mapping"):
            load_policy(str(p))

    def test_human_gate_not_list(self, tmp_path):
        p = _write_policy(tmp_path, "version: 1\nhard_reject: []\npenalties: {}\nhuman_gate_required: 'not-a-list'\n")
        with pytest.raises(PolicyError, match="must be a list"):
            load_policy(str(p))

    def test_penalty_block_not_mapping(self, tmp_path):
        p = _write_policy(tmp_path, "version: 1\nhard_reject: []\npenalties:\n  bad: 'not-a-map'\nhuman_gate_required: []\n")
        with pytest.raises(PolicyError, match="must be a mapping"):
            load_policy(str(p))

    def test_penalty_missing_threshold(self, tmp_path):
        p = _write_policy(tmp_path, "version: 1\nhard_reject: []\npenalties:\n  bad:\n    weight: 1\nhuman_gate_required: []\n")
        with pytest.raises(PolicyError, match="missing 'threshold' or 'weight'"):
            load_policy(str(p))

    def test_penalty_missing_weight(self, tmp_path):
        p = _write_policy(tmp_path, "version: 1\nhard_reject: []\npenalties:\n  bad:\n    threshold: 10\nhuman_gate_required: []\n")
        with pytest.raises(PolicyError, match="missing 'threshold' or 'weight'"):
            load_policy(str(p))

    def test_penalty_weight_not_int(self, tmp_path):
        p = _write_policy(tmp_path, "version: 1\nhard_reject: []\npenalties:\n  bad:\n    threshold: 10\n    weight: 'ten'\nhuman_gate_required: []\n")
        with pytest.raises(PolicyError, match="weight must be an integer"):
            load_policy(str(p))

    def test_hard_reject_entry_not_mapping(self, tmp_path):
        p = _write_policy(tmp_path, "version: 1\nhard_reject:\n  - not-a-dict\npenalties: {}\nhuman_gate_required: []\n")
        with pytest.raises(PolicyError, match="must be a mapping"):
            load_policy(str(p))

    def test_human_gate_entry_not_mapping(self, tmp_path):
        p = _write_policy(tmp_path, "version: 1\nhard_reject: []\npenalties: {}\nhuman_gate_required:\n  - not-a-dict\n")
        with pytest.raises(PolicyError, match="must be a mapping"):
            load_policy(str(p))

    def test_hard_reject_entry_multi_key_rejected(self, tmp_path):
        """Multi-key dict in hard_reject is rejected (canonical single-key only)."""
        p = _write_policy(tmp_path, "version: 1\nhard_reject:\n  - key: a\n    other: b\npenalties: {}\nhuman_gate_required: []\n")
        with pytest.raises(PolicyError, match="single-key mapping"):
            load_policy(str(p))

    def test_hard_reject_entry_single_key_accepted(self, tmp_path):
        """Single-key dict in hard_reject is accepted."""
        p = _write_policy(tmp_path, "version: 1\nhard_reject:\n  - repo_inaccessible: true\npenalties: {}\nhuman_gate_required: []\n")
        policy = load_policy(str(p))
        assert len(policy.hard_reject) == 1
        assert policy.hard_reject[0].key == "repo_inaccessible"
        assert policy.hard_reject[0].value is True

    def test_human_gate_entry_multi_key_rejected(self, tmp_path):
        """Multi-key dict in human_gate_required is rejected."""
        p = _write_policy(tmp_path, "version: 1\nhard_reject: []\npenalties: {}\nhuman_gate_required:\n  - key: a\n    other: b\n")
        with pytest.raises(PolicyError, match="single-key mapping"):
            load_policy(str(p))


# ---------------------------------------------------------------------------
# File issues
# ---------------------------------------------------------------------------

class TestFileNotFound:
    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(PolicyError, match="not found"):
            load_policy(str(tmp_path / "nonexistent.yaml"))


# ---------------------------------------------------------------------------
# Fail-closed
# ---------------------------------------------------------------------------

class TestFailClosed:
    def test_no_silent_fallback_on_invalid(self, tmp_path):
        """Invalid policy raises PolicyError; no fallback to default."""
        p = _write_policy(tmp_path, "{{{broken\n")
        with pytest.raises(PolicyError):
            load_policy(str(p))
