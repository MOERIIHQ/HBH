"""
HBH Structured JSON Logging.

Phase 0: machine-readable JSON logging to stderr.
No external logging service dependency.
"""

from __future__ import annotations

import json
import sys
import threading
from datetime import datetime, timezone
from typing import Any

from hbh.core.config import Config

_JSON_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(
    *,
    level: str,
    event: str,
    message: str,
    actor: str | None = None,
    entity_id: str | None = None,
    state: str | None = None,
    from_state: str | None = None,
    to_state: str | None = None,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
    **extra: Any,
) -> None:
    """
    Emit one structured JSON log line.

    Always includes: timestamp, level, event, actor, message.
    Optional fields are included only when truthy / provided.
    """
    record: dict[str, Any] = {
        "timestamp": _now_iso(),
        "level": level,
        "event": event,
        "actor": actor or "system",
        "message": message,
    }

    if entity_id:
        record["entity_id"] = entity_id
    if state:
        record["state"] = state
    if from_state:
        record["from_state"] = from_state
    if to_state:
        record["to_state"] = to_state
    if reason:
        record["reason"] = reason
    if metadata:
        record["metadata"] = metadata

    record.update(extra)

    line = json.dumps(record, default=str, ensure_ascii=False)

    with _JSON_LOCK:
        sys.stderr.write(line + "\n")
        sys.stderr.flush()


def log_info(*, event: str, message: str, **kwargs: Any) -> None:
    log(level="INFO", event=event, message=message, **kwargs)


def log_warn(*, event: str, message: str, **kwargs: Any) -> None:
    log(level="WARN", event=event, message=message, **kwargs)


def log_error(*, event: str, message: str, **kwargs: Any) -> None:
    log(level="ERROR", event=event, message=message, **kwargs)


class AuditLogger:
    """
    Thin wrapper: structured log + optional event-table write.

    Phase 0: writes structured logs to stderr always. When a Database
    handle is provided, also persists events to the events table so
    the audit trail survives across sessions.
    """

    def __init__(self, config: Config, db: Database | None = None) -> None:
        self._config = config
        self._db = db

    def transition(
        self,
        *,
        entity_id: str,
        actor: str,
        from_state: str,
        to_state: str,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        log(
            level="INFO",
            event="state_transition",
            message=f"{from_state} -> {to_state}",
            actor=actor,
            entity_id=entity_id,
            from_state=from_state,
            to_state=to_state,
            reason=reason,
            metadata=metadata,
        )
        if self._db is not None:
            from hbh.core.database import insert_event
            insert_event(
                self._db,
                entity_id=entity_id,
                actor=actor,
                from_state=from_state,
                to_state=to_state,
                reason=reason,
                metadata=metadata,
            )

    def decision(
        self,
        *,
        entity_id: str,
        actor: str,
        decision: str,
        reasons: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        log(
            level="INFO",
            event="decision",
            message=decision,
            actor=actor,
            entity_id=entity_id,
            decision=decision,
            reason="; ".join(reasons),
            metadata=metadata,
        )
        if self._db is not None:
            from hbh.core.database import insert_event
            insert_event(
                self._db,
                entity_id=entity_id,
                actor=actor,
                reason="; ".join(reasons),
                metadata=metadata,
            )
