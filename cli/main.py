"""
HBH CLI — Phase 0.

Subcommands:
    init        Initialize HBH home, database, schema, policy.
    status      Show HBH internal status.
    policy show Show loaded policy (readable).
"""

from __future__ import annotations

import sys
from pathlib import Path

from hbh.core.config import load_config
from hbh.core.database import Database, ensure_schema, is_initialized, validate_schema_version
from hbh.core.policy import load_policy, show_policy, PolicyError


def _usage() -> None:
    sys.stderr.write(
        "Usage: python -m hbh.cli <command>\n"
        "Commands: init, status, policy show\n"
    )


def run() -> int:
    args = sys.argv[1:]

    if not args:
        _usage()
        return 2

    command = args[0]
    subcommand = args[1] if len(args) > 1 else None

    if command == "init":
        return _cmd_init(subcommand)
    elif command == "status":
        return _cmd_status(subcommand)
    elif command == "policy":
        if subcommand != "show":
            sys.stderr.write("Usage: hbh policy show\n")
            return 2
        return _cmd_policy_show()
    else:
        _usage()
        return 2


def _cmd_init(_subcommand: str | None) -> int:
    config = load_config()
    config.ensure_home()

    from datetime import datetime, timezone
    db_path = config.db_path

    db = Database.create(config)

    try:
        ensure_schema(db)
        db.close()
    except Exception as e:
        sys.stderr.write(f"ERROR: database initialization failed: {e}\n")
        try:
            db.close()
        except Exception:
            pass
        return 1

    sys.stdout.write(f"HBH initialized.\n")
    sys.stdout.write(f"Home: {config.home}\n")
    sys.stdout.write(f"Database: {db_path}\n")
    sys.stdout.write(f"Schema: v1\n")
    return 0


def _cmd_status(_subcommand: str | None) -> int:
    config = load_config()
    db_path = config.db_path

    # Check database
    if not Path(db_path).is_file():
        sys.stderr.write("ERROR: database not found. Run 'hbh init' first.\n")
        return 1

    try:
        db = Database.connect(db_path)
    except Exception as e:
        sys.stderr.write(f"ERROR: cannot open database: {e}\n")
        return 1

    try:
        validate_schema_version(db)
        initialized = is_initialized(db)
        schema_version = 1 if initialized else 0
    except Exception as e:
        db.close()
        sys.stderr.write(f"ERROR: database validation failed: {e}\n")
        return 1

    db.close()

    # Check policy
    policy_ok = _check_policy(config)

    sys.stdout.write("HBH\n")
    sys.stdout.write(f"Database: {'OK' if initialized else 'NOT INITIALIZED'}\n")
    sys.stdout.write(f"Schema: v{schema_version}\n")
    sys.stdout.write(f"Policy: {'OK' if policy_ok else 'INVALID'}\n")

    return 0 if (initialized and policy_ok) else 1


def _check_policy(config) -> bool:
    try:
        policy = load_policy(config.policy_path)
        return True
    except PolicyError:
        return False


def _cmd_policy_show() -> int:
    config = load_config()

    try:
        policy = load_policy(config.policy_path)
    except PolicyError as e:
        sys.stderr.write(f"ERROR: Policy validation failed: {e}\n")
        return 1

    sys.stdout.write(show_policy(policy))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(run())
