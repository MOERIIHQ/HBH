"""
HBH State Machine — Phase 0.

Explicit, deterministic state machine for HBH bounty lifecycle.
Invalid transitions are rejected. Terminal states are protected.
"""

from __future__ import annotations

from dataclasses import dataclass

from hbh.core.models import BountyStatus
from hbh.core.audit import AuditLogger
from hbh.core.database import insert_event


# ---------------------------------------------------------------------------
# Transition table
# ---------------------------------------------------------------------------

# Directed graph: from_state -> set of allowed to_states
# Each source can have BOTH its forward workflow target(s) AND
# its failure/terminal targets. They are merged after construction.

_WORKFLOW_TRANSITIONS: dict[BountyStatus, frozenset[BountyStatus]] = {
    BountyStatus.DISCOVERED: frozenset({BountyStatus.PROFILED}),
    BountyStatus.PROFILED: frozenset({BountyStatus.TRIAGED}),
    BountyStatus.TRIAGED: frozenset({BountyStatus.SELECTED}),
    BountyStatus.SELECTED: frozenset({BountyStatus.CONTEXT_READY}),
    BountyStatus.CONTEXT_READY: frozenset({BountyStatus.IMPLEMENTING}),
    BountyStatus.IMPLEMENTING: frozenset({BountyStatus.VALIDATING}),
    BountyStatus.VALIDATING: frozenset({BountyStatus.READY_FOR_REVIEW}),
    BountyStatus.READY_FOR_REVIEW: frozenset({BountyStatus.APPROVED}),
    BountyStatus.APPROVED: frozenset({BountyStatus.SUBMITTED}),
    BountyStatus.SUBMITTED: frozenset({BountyStatus.ACCEPTED, BountyStatus.REJECTED}),
}

_FAILURE_TRANSITIONS: dict[BountyStatus, frozenset[BountyStatus]] = {
    # Any non-terminal state can transition to a failure/terminal state
    BountyStatus.DISCOVERED: frozenset({BountyStatus.ABORTED, BountyStatus.FAILED, BountyStatus.EXPIRED}),
    BountyStatus.PROFILED: frozenset({BountyStatus.ABORTED, BountyStatus.FAILED, BountyStatus.EXPIRED}),
    BountyStatus.TRIAGED: frozenset({BountyStatus.ABORTED, BountyStatus.FAILED, BountyStatus.EXPIRED}),
    BountyStatus.SELECTED: frozenset({BountyStatus.ABORTED, BountyStatus.FAILED, BountyStatus.EXPIRED}),
    BountyStatus.CONTEXT_READY: frozenset({BountyStatus.ABORTED, BountyStatus.FAILED, BountyStatus.EXPIRED}),
    BountyStatus.IMPLEMENTING: frozenset({BountyStatus.ABORTED, BountyStatus.FAILED, BountyStatus.EXPIRED}),
    BountyStatus.VALIDATING: frozenset({BountyStatus.ABORTED, BountyStatus.FAILED, BountyStatus.EXPIRED}),
    BountyStatus.READY_FOR_REVIEW: frozenset({BountyStatus.ABORTED, BountyStatus.FAILED, BountyStatus.EXPIRED}),
    BountyStatus.APPROVED: frozenset({BountyStatus.ABORTED, BountyStatus.FAILED, BountyStatus.EXPIRED}),
    BountyStatus.SUBMITTED: frozenset({BountyStatus.ABORTED, BountyStatus.FAILED, BountyStatus.EXPIRED}),
}

# Merged per-source for fast lookup: workflow + failure targets combined
_TRANSITION_MAP: dict[BountyStatus, frozenset[BountyStatus]] = {}
for src in list(_WORKFLOW_TRANSITIONS.keys()) + list(_FAILURE_TRANSITIONS.keys()):
    targets: set[BountyStatus] = set()
    targets.update(_WORKFLOW_TRANSITIONS.get(src, frozenset()))
    targets.update(_FAILURE_TRANSITIONS.get(src, frozenset()))
    _TRANSITION_MAP[src] = frozenset(targets)

TERMINAL_STATES: frozenset[BountyStatus] = frozenset({
    BountyStatus.ACCEPTED,
    BountyStatus.REJECTED,
    BountyStatus.ABORTED,
    BountyStatus.FAILED,
    BountyStatus.EXPIRED,
})

_VALID_ACTORS: frozenset[str] = frozenset({
    "system",
    "policy_engine",
    "triage_engine",
    "human",
    "executor",
    "validation_engine",
    "discovery_engine",
    "repository_profiler",
})


@dataclass(frozen=True)
class Transition:
    from_state: BountyStatus
    to_state: BountyStatus


def is_terminal(state: BountyStatus) -> bool:
    return state in TERMINAL_STATES


def is_valid_transition(from_state: BountyStatus, to_state: BountyStatus) -> bool:
    """Return True if the transition is allowed by the state machine."""
    if from_state not in _TRANSITION_MAP:
        return False
    if to_state not in _TRANSITION_MAP[from_state]:
        return False
    return True


def can_exit_terminal(state: BountyStatus) -> bool:
    """Return True if the state is NOT terminal (can be exited via normal workflow)."""
    return not is_terminal(state)


def validate_transition(from_state: BountyStatus, to_state: BountyStatus) -> None:
    """
    Validate a transition. Raises ValueError on invalid transition
    or attempt to leave a terminal state.
    """
    if from_state not in _TRANSITION_MAP:
        raise ValueError(f"Unknown source state: {from_state.value}")

    if to_state not in _TRANSITION_MAP[from_state]:
        raise ValueError(
            f"Invalid transition: {from_state.value} -> {to_state.value}. "
            f"Allowed targets: {sorted(t.value for t in _TRANSITION_MAP[from_state])}"
        )


def record_transition(
    logger: AuditLogger,
    *,
    entity_id: str,
    actor: str,
    from_state: BountyStatus,
    to_state: BountyStatus,
    reason: str,
    db: Database | None = None,
) -> Transition:
    """
    Validate + record a state transition.

    Raises ValueError if invalid. On success, emits a structured log
    event (and optionally persists to the events table if db is given),
    then returns the Transition.
    """
    validate_transition(from_state, to_state)

    if actor not in _VALID_ACTORS:
        raise ValueError(f"Unknown actor: {actor}. Allowed: {sorted(_VALID_ACTORS)}")

    logger.transition(
        entity_id=entity_id,
        actor=actor,
        from_state=from_state.value,
        to_state=to_state.value,
        reason=reason,
    )

    if db is not None:
        insert_event(
            db,
            entity_id=entity_id,
            actor=actor,
            from_state=from_state.value,
            to_state=to_state.value,
            reason=reason,
        )

    return Transition(from_state=from_state, to_state=to_state)
