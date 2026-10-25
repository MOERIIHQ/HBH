"""
Tests for hbh.core.audit — Phase 0.
"""

import json
import sys
import tempfile

import pytest

from hbh.core.audit import log, log_info, log_warn, log_error, AuditLogger
from hbh.core.config import load_config


class TestStructuredLog:
    def test_log_emits_json_line(self, capsys):
        log(
            level="INFO",
            event="test_event",
            message="test message",
            actor="system",
        )
        captured = capsys.readouterr()
        line = captured.err.strip().split("\n")[-1]
        record = json.loads(line)
        assert record["timestamp"] is not None
        assert record["level"] == "INFO"
        assert record["event"] == "test_event"
        assert record["actor"] == "system"
        assert record["message"] == "test message"

    def test_log_includes_optional_fields(self, capsys):
        log(
            level="WARN",
            event="decision",
            message="REJECT",
            actor="policy_engine",
            entity_id="b-1",
            from_state="TRIAGED",
            to_state="REJECTED",
            reason="below_threshold",
            metadata={"score": 0.2},
        )
        captured = capsys.readouterr()
        line = captured.err.strip().split("\n")[-1]
        record = json.loads(line)
        assert record["level"] == "WARN"
        assert record["entity_id"] == "b-1"
        assert record["from_state"] == "TRIAGED"
        assert record["to_state"] == "REJECTED"
        assert record["reason"] == "below_threshold"
        assert record["metadata"] == {"score": 0.2}

    def test_log_info_shortcut(self, capsys):
        log_info(event="boot", message="HBH starting")
        captured = capsys.readouterr()
        line = captured.err.strip().split("\n")[-1]
        record = json.loads(line)
        assert record["level"] == "INFO"
        assert record["event"] == "boot"

    def test_log_warn_shortcut(self, capsys):
        log_warn(event="config_warning", message="unknown key")
        captured = capsys.readouterr()
        line = captured.err.strip().split("\n")[-1]
        record = json.loads(line)
        assert record["level"] == "WARN"

    def test_log_error_shortcut(self, capsys):
        log_error(event="config_error", message="failed to load")
        captured = capsys.readouterr()
        line = captured.err.strip().split("\n")[-1]
        record = json.loads(line)
        assert record["level"] == "ERROR"


class TestAuditLogger:
    def test_transition_emits_correct_event(self, capsys, tmp_path):
        cfg = load_config(hbhome=str(tmp_path))
        logger = AuditLogger(cfg)

        logger.transition(
            entity_id="b-1",
            actor="policy_engine",
            from_state="DISCOVERED",
            to_state="PROFILED",
            reason="profile_started",
        )

        captured = capsys.readouterr()
        line = captured.err.strip().split("\n")[-1]
        record = json.loads(line)
        assert record["event"] == "state_transition"
        assert record["entity_id"] == "b-1"
        assert record["actor"] == "policy_engine"
        assert record["from_state"] == "DISCOVERED"
        assert record["to_state"] == "PROFILED"
        assert record["reason"] == "profile_started"

    def test_decision_emits_correct_event(self, capsys, tmp_path):
        cfg = load_config(hbhome=str(tmp_path))
        logger = AuditLogger(cfg)

        logger.decision(
            entity_id="b-1",
            actor="triage_engine",
            decision="REJECT",
            reasons=["below_expected_value", "high_risk"],
            metadata={"score": 0.3},
        )

        captured = capsys.readouterr()
        line = captured.err.strip().split("\n")[-1]
        record = json.loads(line)
        assert record["event"] == "decision"
        assert record["decision"] == "REJECT"
        assert "below_expected_value" in record["reason"]
        assert "high_risk" in record["reason"]
