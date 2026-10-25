"""
HBH Policy — Phase 0.

Declarative YAML policy with schema validation and fail-closed behaviour.
Phase 0 does NOT execute policy scoring; it only loads and validates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from hbh.core.audit import log_error, log_info

# ---------------------------------------------------------------------------
# Policy schema (minimal, declarative)
# ---------------------------------------------------------------------------

SUPPORTED_POLICY_VERSIONS: frozenset[int] = frozenset({1})


@dataclass
class HardRejectRule:
    """Single hard-reject rule: key -> expected value."""
    key: str
    value: Any


@dataclass
class PenaltyRule:
    """Single penalty rule with threshold and weight."""
    threshold: int | float | str
    weight: int


@dataclass
class PenaltyBlock:
    """Named penalty block (e.g. inactive_days)."""
    threshold: int | float | str
    weight: int


@dataclass
class HumanGateRule:
    """Single human-gate trigger condition."""
    key: str
    value: Any


@dataclass
class Policy:
    """Loaded, validated policy snapshot. Immutable after load."""
    version: int
    hard_reject: list[HardRejectRule] = field(default_factory=list)
    penalties: dict[str, PenaltyBlock] = field(default_factory=dict)
    human_gate_required: list[HumanGateRule] = field(default_factory=list)

    def hard_reject_keys(self) -> list[str]:
        return [r.key for r in self.hard_reject]

    def human_gate_keys(self) -> list[str]:
        return [r.key for r in self.human_gate_required]


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------

class PolicyError(Exception):
    """Raised when policy is invalid, unsupported, or missing."""
    pass


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_policy(path: str | Path) -> Policy:
    """
    Load and validate a YAML policy file.

    Fail-closed: any validation error raises PolicyError; never
    silently falls back to an arbitrary default.
    """
    path = Path(path)

    if not path.is_file():
        raise PolicyError(f"Policy file not found: {path}")

    raw = _read_yaml(path)
    schema = _validate_schema(raw, path)
    return _build_policy(schema, path)


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as e:
        raise PolicyError(f"Invalid YAML in policy file {path}: {e}") from e

    if not isinstance(data, dict):
        raise PolicyError(f"Policy file {path} must contain a YAML mapping at top level")

    return data


def _validate_hard_reject(raw: list[Any], path: Path) -> list[dict[str, Any]]:
    """Validate hard_reject list: each item must be a single-key mapping.

    Canonical format: {condition: expected_value}
    Example: {repo_inaccessible: true}
             {estimated_size_kb: "> 500000"}
    """
    normalized: list[dict[str, Any]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise PolicyError(f"Policy file {path} hard_reject[{i}] must be a mapping")
        if len(item) != 1:
            raise PolicyError(
                f"Policy file {path} hard_reject[{i}] must be a single-key mapping"
            )
        key, value = next(iter(item.items()))
        normalized.append({"key": key, "value": value})
    return normalized


def _validate_human_gate(raw: list[Any], path: Path) -> list[dict[str, Any]]:
    """Validate human_gate_required list: each item must be a single-key mapping.

    Canonical format: {trigger: condition}
    Example: {credential_write_required: true}
    """
    normalized: list[dict[str, Any]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise PolicyError(f"Policy file {path} human_gate_required[{i}] must be a mapping")
        if len(item) != 1:
            raise PolicyError(
                f"Policy file {path} human_gate_required[{i}] must be a single-key mapping"
            )
        key, value = next(iter(item.items()))
        normalized.append({"key": key, "value": value})
    return normalized


def _validate_schema(raw: dict[str, Any], path: Path) -> dict[str, Any]:
    """Validate top-level structure. Raises PolicyError on failure."""
    # version
    version = raw.get("version")
    if version is None:
        raise PolicyError(f"Policy file {path} missing required field 'version'")
    if not isinstance(version, int):
        raise PolicyError(f"Policy file {path} field 'version' must be an integer, got {type(version).__name__}")
    if version not in SUPPORTED_POLICY_VERSIONS:
        raise PolicyError(
            f"Policy file {path} version {version} not supported. "
            f"Supported versions: {sorted(SUPPORTED_POLICY_VERSIONS)}"
        )

    # hard_reject
    hard_reject_raw = raw.get("hard_reject")
    if hard_reject_raw is None:
        raise PolicyError(f"Policy file {path} missing required field 'hard_reject'")
    if not isinstance(hard_reject_raw, list):
        raise PolicyError(f"Policy file {path} field 'hard_reject' must be a list")
    hard_reject_normalized = _validate_hard_reject(hard_reject_raw, path)

    # penalties
    penalties_raw = raw.get("penalties")
    if penalties_raw is None:
        raise PolicyError(f"Policy file {path} missing required field 'penalties'")
    if not isinstance(penalties_raw, dict):
        raise PolicyError(f"Policy file {path} field 'penalties' must be a mapping")
    for name, block in penalties_raw.items():
        if not isinstance(block, dict):
            raise PolicyError(f"Policy file {path} penalties.{name} must be a mapping")
        if "threshold" not in block or "weight" not in block:
            raise PolicyError(f"Policy file {path} penalties.{name} missing 'threshold' or 'weight'")
        if not isinstance(block["weight"], int):
            raise PolicyError(f"Policy file {path} penalties.{name}.weight must be an integer")

    # human_gate_required
    human_gate_raw = raw.get("human_gate_required")
    if human_gate_raw is None:
        raise PolicyError(f"Policy file {path} missing required field 'human_gate_required'")
    if not isinstance(human_gate_raw, list):
        raise PolicyError(f"Policy file {path} field 'human_gate_required' must be a list")
    human_gate_normalized = _validate_human_gate(human_gate_raw, path)

    return {
        "version": version,
        "hard_reject": hard_reject_normalized,
        "penalties": penalties_raw,
        "human_gate_required": human_gate_normalized,
    }


def _build_policy(raw: dict[str, Any], path: Path) -> Policy:
    version = raw["version"]

    hard_reject = [
        HardRejectRule(key=item["key"], value=item["value"])
        for item in raw["hard_reject"]  # sudah ternormalisasi oleh _validate_schema
    ]

    penalties: dict[str, PenaltyBlock] = {}
    for name, block in raw["penalties"].items():
        penalties[name] = PenaltyBlock(
            threshold=block["threshold"],
            weight=block["weight"],
        )

    human_gate = [
        HumanGateRule(key=item["key"], value=item["value"])
        for item in raw["human_gate_required"]  # sudah ternormalisasi
    ]

    return Policy(
        version=version,
        hard_reject=hard_reject,
        penalties=penalties,
        human_gate_required=human_gate,
    )


def show_policy(policy: Policy) -> str:
    """Return a readable representation of the loaded policy."""
    lines: list[str] = []
    lines.append(f"Policy version: {policy.version}")
    lines.append("")
    lines.append("hard_reject:")
    for rule in policy.hard_reject:
        lines.append(f"  - {rule.key}: {rule.value}")
    lines.append("")
    lines.append("penalties:")
    if not policy.penalties:
        lines.append("  (none)")
    else:
        for name, block in policy.penalties.items():
            lines.append(f"  {name}:")
            lines.append(f"    threshold: {block.threshold}")
            lines.append(f"    weight: {block.weight}")
    lines.append("")
    lines.append("human_gate_required:")
    for rule in policy.human_gate_required:
        lines.append(f"  - {rule.key}: {rule.value}")
    return "\n".join(lines)
