"""
HBH Domain Models — Phase 0.

Passive types shared across core modules. No behaviour, no external
dependency. ContextPackage stays in its own module (already LOCKED).
"""

from __future__ import annotations

from enum import Enum


class BountyStatus(Enum):
    UNKNOWN = "unknown"
    DISCOVERED = "discovered"
    PROFILED = "profiled"
    TRIAGED = "triaged"
    SELECTED = "selected"
    CONTEXT_READY = "context_ready"
    IMPLEMENTING = "implementing"
    VALIDATING = "validating"
    READY_FOR_REVIEW = "ready_for_review"
    APPROVED = "approved"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    ABORTED = "aborted"
    FAILED = "failed"
    EXPIRED = "expired"


class ExecutionStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    ABORTED = "aborted"


class ValidationStatus(Enum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"


class PRStatus(Enum):
    NONE = "none"
    OPEN = "open"
    MERGED = "merged"
    CLOSED = "closed"
