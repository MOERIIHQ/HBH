"""
Tests for hbh.core.state_machine — Phase 0.
"""

import pytest

from hbh.core.state_machine import (
    BountyStatus,
    is_terminal,
    is_valid_transition,
    can_exit_terminal,
    validate_transition,
    record_transition,
    Transition,
)
from hbh.core.audit import AuditLogger
from hbh.core.config import load_config


class TestTerminalStates:
    def test_accepted_is_terminal(self):
        assert is_terminal(BountyStatus.ACCEPTED)

    def test_rejected_is_terminal(self):
        assert is_terminal(BountyStatus.REJECTED)

    def test_aborted_is_terminal(self):
        assert is_terminal(BountyStatus.ABORTED)

    def test_failed_is_terminal(self):
        assert is_terminal(BountyStatus.FAILED)

    def test_expired_is_terminal(self):
        assert is_terminal(BountyStatus.EXPIRED)

    def test_discovered_is_not_terminal(self):
        assert not is_terminal(BountyStatus.DISCOVERED)

    def test_profiled_is_not_terminal(self):
        assert not is_terminal(BountyStatus.PROFILED)

    def test_can_exit_terminal_returns_false(self):
        assert can_exit_terminal(BountyStatus.ACCEPTED) is False
        assert can_exit_terminal(BountyStatus.REJECTED) is False
        assert can_exit_terminal(BountyStatus.ABORTED) is False

    def test_can_exit_non_terminal_returns_true(self):
        # Non-terminal states CAN be exited via normal workflow.
        assert can_exit_terminal(BountyStatus.DISCOVERED) is True
        assert can_exit_terminal(BountyStatus.PROFILED) is True


class TestValidTransitions:
    def test_discovered_to_profiled(self):
        assert is_valid_transition(BountyStatus.DISCOVERED, BountyStatus.PROFILED)

    def test_profiled_to_triaged(self):
        assert is_valid_transition(BountyStatus.PROFILED, BountyStatus.TRIAGED)

    def test_triaged_to_selected(self):
        assert is_valid_transition(BountyStatus.TRIAGED, BountyStatus.SELECTED)

    def test_selected_to_context_ready(self):
        assert is_valid_transition(BountyStatus.SELECTED, BountyStatus.CONTEXT_READY)

    def test_context_ready_to_implementing(self):
        assert is_valid_transition(BountyStatus.CONTEXT_READY, BountyStatus.IMPLEMENTING)

    def test_implementing_to_validating(self):
        assert is_valid_transition(BountyStatus.IMPLEMENTING, BountyStatus.VALIDATING)

    def test_validating_to_ready_for_review(self):
        assert is_valid_transition(BountyStatus.VALIDATING, BountyStatus.READY_FOR_REVIEW)

    def test_ready_for_review_to_approved(self):
        assert is_valid_transition(BountyStatus.READY_FOR_REVIEW, BountyStatus.APPROVED)

    def test_approved_to_submitted(self):
        assert is_valid_transition(BountyStatus.APPROVED, BountyStatus.SUBMITTED)

    def test_submitted_to_accepted(self):
        assert is_valid_transition(BountyStatus.SUBMITTED, BountyStatus.ACCEPTED)

    def test_submitted_to_rejected(self):
        assert is_valid_transition(BountyStatus.SUBMITTED, BountyStatus.REJECTED)

    def test_failure_transitions(self):
        assert is_valid_transition(BountyStatus.DISCOVERED, BountyStatus.FAILED)
        assert is_valid_transition(BountyStatus.PROFILED, BountyStatus.ABORTED)
        assert is_valid_transition(BountyStatus.TRIAGED, BountyStatus.EXPIRED)


class TestInvalidTransitions:
    def test_discovered_to_accepted_invalid(self):
        assert not is_valid_transition(BountyStatus.DISCOVERED, BountyStatus.ACCEPTED)

    def test_accepted_to_implementing_invalid(self):
        assert not is_valid_transition(BountyStatus.ACCEPTED, BountyStatus.IMPLEMENTING)

    def test_reverse_transition_invalid(self):
        assert not is_valid_transition(BountyStatus.PROFILED, BountyStatus.DISCOVERED)

    def test_unknown_target_invalid(self):
        # Use a made-up status not in the transition map
        class FakeStatus:
            value = "fake_state"
        from hbh.core.state_machine import _TRANSITION_MAP
        assert FakeStatus not in _TRANSITION_MAP


class TestValidateTransitionRaises:
    def test_invalid_transition_raises(self):
        with pytest.raises(ValueError, match="Invalid transition"):
            validate_transition(BountyStatus.DISCOVERED, BountyStatus.ACCEPTED)

    def test_unknown_source_state_raises(self):
        with pytest.raises(ValueError, match="Unknown source state"):
            validate_transition(BountyStatus.ACCEPTED, BountyStatus.PROFILED)


class TestRecordTransition:
    def test_records_valid_transition(self, tmp_path):
        cfg = load_config(
            hbhome=str(tmp_path),
            db_path=str(tmp_path / "sm_test.db"),
            policy_path="dummy",
        )
        from hbh.core.database import Database, ensure_schema
        db = Database.create(cfg)
        ensure_schema(db)
        logger = AuditLogger(cfg)

        transition = record_transition(
            logger,
            entity_id="b-1",
            actor="policy_engine",
            from_state=BountyStatus.DISCOVERED,
            to_state=BountyStatus.PROFILED,
            reason="policy_check_passed",
        )

        assert isinstance(transition, Transition)
        assert transition.from_state == BountyStatus.DISCOVERED
        assert transition.to_state == BountyStatus.PROFILED
        db.close()

    def test_records_event_in_database(self, tmp_path):
        cfg = load_config(
            hbhome=str(tmp_path),
            db_path=str(tmp_path / "sm_audit.db"),
            policy_path="dummy",
        )
        from hbh.core.database import Database, ensure_schema
        db = Database.create(cfg)
        ensure_schema(db)
        logger = AuditLogger(cfg)

        record_transition(
            logger,
            entity_id="b-2",
            actor="triage_engine",
            from_state=BountyStatus.PROFILED,
            to_state=BountyStatus.TRIAGED,
            reason="triaged",
            db=db,
        )

        row = db.connection.execute(
            "SELECT * FROM events ORDER BY event_id DESC LIMIT 1"
        ).fetchone()
        assert row["entity_id"] == "b-2"
        assert row["actor"] == "triage_engine"
        assert row["from_state"] == "profiled"
        assert row["to_state"] == "triaged"

        db.close()

    def test_invalid_actor_raises(self, tmp_path):
        cfg = load_config(
            hbhome=str(tmp_path),
            db_path=str(tmp_path / "sm_actor.db"),
            policy_path="dummy",
        )
        from hbh.core.database import Database, ensure_schema
        db = Database.create(cfg)
        ensure_schema(db)
        logger = AuditLogger(cfg)

        with pytest.raises(ValueError, match="Unknown actor"):
            record_transition(
                logger,
                entity_id="b-3",
                actor="invalid_actor",
                from_state=BountyStatus.DISCOVERED,
                to_state=BountyStatus.PROFILED,
                reason="test",
            )
        db.close()
