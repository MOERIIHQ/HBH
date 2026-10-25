"""
Tests for hbh.discovery.runtime — Phase 1b-GH-2C.

Focused tests for the DiscoveryRuntime: configuration mapping,
enabled/disabled semantics, missing adapter handling,
multi-adapter execution, failure isolation, deterministic order,
and DiscoveryEngine integration.
"""

from __future__ import annotations

import inspect
import json
import os
import tempfile
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from hbh.core.config import Config
from hbh.core.database import Database, ensure_schema
from hbh.discovery.engine import (
    DiscoveryEngine,
    DiscoveryRunResult,
    RunStatus,
    create_discovery_engine,
)
from hbh.discovery.models import (
    ADAPTER_CONTRACT_VERSION,
    AdapterResult,
    AdapterStatus,
    BountyCandidate,
    DiscoveryAdapter,
    RunContext,
    make_bounty_candidate,
    make_run_context,
    make_adapter_result,
)
from hbh.discovery.registry import AdapterRegistry
from hbh.discovery.runtime import (
    DiscoveryRuntime,
    RuntimeMissingAdapter,
    make_fake_adapter,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_dir(tmp_path):
    """Return a Path to a temporary directory."""
    return tmp_path


@pytest.fixture
def config(tmp_dir):
    """Build a Config with a temporary HBH home and discovery_config path."""
    config_file = tmp_dir / "discovery_config.yaml"
    config_file.write_text("version: 1\nsources: {}\n", encoding="utf-8")
    return Config(hbhome=str(tmp_dir), discovery_config_path=str(config_file))


@pytest.fixture
def db(config):
    """Create a Database with schema."""
    db = Database.create(config)
    ensure_schema(db)
    yield db
    db.close()


@pytest.fixture
def registry():
    """Fresh AdapterRegistry."""
    return AdapterRegistry()


@pytest.fixture
def runtime(registry):
    """Fresh DiscoveryRuntime."""
    return DiscoveryRuntime(registry=registry)


def write_discovery_config(tmp_dir, content):
    """Write discovery_config.yaml content to tmp_dir and return the path."""
    path = tmp_dir / "discovery_config.yaml"
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Fake adapter helpers
# ---------------------------------------------------------------------------


def _success_adapter(source: str, *, candidates=None, version=ADAPTER_CONTRACT_VERSION):
    return make_fake_adapter(
        source,
        status=AdapterStatus.SUCCESS,
        candidates=candidates,
        adapter_version=version,
    )


def _failed_adapter(source: str, *, error="simulated failure", version=ADAPTER_CONTRACT_VERSION):
    return make_fake_adapter(
        source,
        status=AdapterStatus.FAILED,
        error=error,
        adapter_version=version,
    )


def _candidate(source="github", source_id="123", *, title="Test"):
    return make_bounty_candidate(
        source=source,
        source_id=source_id,
        title=title,
        repository_url=f"https://github.com/owner/repo",
        issue_url=f"https://github.com/owner/repo/issues/{source_id}",
    )


# ===================================================================
# Configuration mapping tests
# ===================================================================


class TestConfigurationMapping:
    def test_enabled_source_selected(self, tmp_dir, registry):
        config_file = write_discovery_config(
            tmp_dir,
            """
            version: 1
            sources:
              github:
                enabled: true
                repositories:
                  - owner/repo
            """,
        )
        cfg = Config(discovery_config_path=str(config_file))
        registry.register(_success_adapter("github"))
        result = DiscoveryRuntime(registry=registry).run(config=cfg)
        assert result.status == RunStatus.SUCCESS
        assert result.adapters_total == 1
        assert result.adapters_succeeded == 1

    def test_disabled_source_not_selected(self, tmp_dir, registry):
        config_file = write_discovery_config(
            tmp_dir,
            """
            version: 1
            sources:
              github:
                enabled: false
            """,
        )
        cfg = Config(discovery_config_path=str(config_file))
        registry.register(_success_adapter("github"))
        result = DiscoveryRuntime(registry=registry).run(config=cfg)
        assert result.status == RunStatus.FAILED
        assert result.adapters_total == 0

    def test_multiple_enabled_sources_all_selected(self, tmp_dir, registry, db):
        config_file = write_discovery_config(
            tmp_dir,
            """
            version: 1
            sources:
              github:
                enabled: true
                repositories:
                  - owner/repo
              algora:
                enabled: true
                organizations:
                  - org1
            """,
        )
        cfg = Config(discovery_config_path=str(config_file))
        registry.register(_success_adapter("github", candidates=[_candidate("github", "1")]))
        registry.register(_success_adapter("algora", candidates=[_candidate("algora", "1")]))
        eng = create_discovery_engine(config=cfg, db=db)
        result = DiscoveryRuntime(registry=registry).run(config=cfg, engine=eng)
        assert result.status == RunStatus.SUCCESS
        assert result.adapters_total == 2
        assert result.adapters_succeeded == 2
        row_github = db.connection.execute(
            "SELECT 1 FROM bounties WHERE source = ? AND source_id = ?",
            ("github", "1"),
        ).fetchone()
        row_algora = db.connection.execute(
            "SELECT 1 FROM bounties WHERE source = ? AND source_id = ?",
            ("algora", "1"),
        ).fetchone()
        assert row_github is not None
        assert row_algora is not None


# ===================================================================
# Missing adapter semantics
# ===================================================================


class TestMissingAdapterSemantics:
    def test_enabled_source_no_adapter_raises(self, tmp_dir, registry):
        config_file = write_discovery_config(
            tmp_dir,
            """
            version: 1
            sources:
              github:
                enabled: true
            """,
        )
        cfg = Config(discovery_config_path=str(config_file))
        with pytest.raises(RuntimeError, match="no registered adapter"):
            DiscoveryRuntime(registry=registry).run(config=cfg)

    def test_missing_adapter_is_observable(self, tmp_dir, registry):
        config_file = write_discovery_config(
            tmp_dir,
            """
            version: 1
            sources:
              github:
                enabled: true
            """,
        )
        cfg = Config(discovery_config_path=str(config_file))
        with pytest.raises(RuntimeError) as exc_info:
            DiscoveryRuntime(registry=registry).run(config=cfg)
        assert "github" in str(exc_info.value)
        assert "registered adapter" in str(exc_info.value)

    def test_disabled_source_no_adapter_not_error(self, tmp_dir, registry):
        config_file = write_discovery_config(
            tmp_dir,
            """
            version: 1
            sources:
              github:
                enabled: false
            """,
        )
        cfg = Config(discovery_config_path=str(config_file))
        result = DiscoveryRuntime(registry=registry).run(config=cfg)
        assert result.status == RunStatus.FAILED
        assert result.adapters_total == 0


# ===================================================================
# Single adapter execution tests
# ===================================================================


class TestSingleAdapterExecution:
    def test_single_adapter_success(self, tmp_dir, registry, db):
        config_file = write_discovery_config(
            tmp_dir,
            """
            version: 1
            sources:
              github:
                enabled: true
                repositories:
                  - owner/repo
            """,
        )
        cfg = Config(discovery_config_path=str(config_file))
        registry.register(_success_adapter("github", candidates=[_candidate("github", "1")]))
        eng = create_discovery_engine(config=cfg, db=db)
        result = DiscoveryRuntime(registry=registry).run(config=cfg, engine=eng)
        assert result.status == RunStatus.SUCCESS
        assert result.adapters_total == 1
        assert result.adapters_succeeded == 1
        assert result.candidates_inserted == 1

    def test_single_adapter_success_zero_candidates(self, tmp_dir, registry, db):
        config_file = write_discovery_config(
            tmp_dir,
            """
            version: 1
            sources:
              github:
                enabled: true
            """,
        )
        cfg = Config(discovery_config_path=str(config_file))
        registry.register(_success_adapter("github", candidates=[]))
        eng = create_discovery_engine(config=cfg, db=db)
        result = DiscoveryRuntime(registry=registry).run(config=cfg, engine=eng)
        assert result.status == RunStatus.SUCCESS
        assert result.adapters_succeeded == 1
        assert result.candidates_inserted == 0

    def test_single_adapter_failure(self, tmp_dir, registry, db):
        config_file = write_discovery_config(
            tmp_dir,
            """
            version: 1
            sources:
              github:
                enabled: true
            """,
        )
        cfg = Config(discovery_config_path=str(config_file))
        registry.register(_failed_adapter("github"))
        eng = create_discovery_engine(config=cfg, db=db)
        result = DiscoveryRuntime(registry=registry).run(config=cfg, engine=eng)
        assert result.status == RunStatus.FAILED
        assert result.adapters_total == 1
        assert result.adapters_failed == 1


# ===================================================================
# Multi-adapter execution tests
# ===================================================================


class TestMultiAdapterExecution:
    def test_multiple_adapter_success(self, tmp_dir, registry, db):
        config_file = write_discovery_config(
            tmp_dir,
            """
            version: 1
            sources:
              github:
                enabled: true
              algora:
                enabled: true
            """,
        )
        cfg = Config(discovery_config_path=str(config_file))
        registry.register(_success_adapter("github", candidates=[_candidate("github", "1")]))
        registry.register(_success_adapter("algora", candidates=[_candidate("algora", "1")]))
        eng = create_discovery_engine(config=cfg, db=db)
        result = DiscoveryRuntime(registry=registry).run(config=cfg, engine=eng)
        assert result.status == RunStatus.SUCCESS
        assert result.adapters_total == 2
        assert result.adapters_succeeded == 2
        assert result.candidates_inserted == 2

    def test_all_adapter_failure(self, tmp_dir, registry, db):
        config_file = write_discovery_config(
            tmp_dir,
            """
            version: 1
            sources:
              github:
                enabled: true
              algora:
                enabled: true
            """,
        )
        cfg = Config(discovery_config_path=str(config_file))
        registry.register(_failed_adapter("github"))
        registry.register(_failed_adapter("algora"))
        eng = create_discovery_engine(config=cfg, db=db)
        result = DiscoveryRuntime(registry=registry).run(config=cfg, engine=eng)
        assert result.status == RunStatus.FAILED
        assert result.adapters_total == 2
        assert result.adapters_failed == 2


# ===================================================================
# Partial adapter failure tests
# ===================================================================


class TestPartialAdapterFailure:
    def test_partial_failure_some_succeeded_some_failed(
        self, tmp_dir, registry, db
    ):
        config_file = write_discovery_config(
            tmp_dir,
            """
            version: 1
            sources:
              github:
                enabled: true
              algora:
                enabled: true
            """,
        )
        cfg = Config(discovery_config_path=str(config_file))
        registry.register(_success_adapter("github", candidates=[_candidate("github", "1")]))
        registry.register(_failed_adapter("algora"))
        eng = create_discovery_engine(config=cfg, db=db)
        result = DiscoveryRuntime(registry=registry).run(config=cfg, engine=eng)
        assert result.status == RunStatus.PARTIAL
        assert result.adapters_total == 2
        assert result.adapters_succeeded == 1
        assert result.adapters_failed == 1
        assert result.candidates_inserted == 1


# ===================================================================
# Failure isolation tests
# ===================================================================


class TestFailureIsolation:
    def test_adapter_a_failed_adapter_b_still_executes(
        self, tmp_dir, registry, db
    ):
        config_file = write_discovery_config(
            tmp_dir,
            """
            version: 1
            sources:
              github:
                enabled: true
              algora:
                enabled: true
            """,
        )
        cfg = Config(discovery_config_path=str(config_file))
        registry.register(_failed_adapter("github", error="github failed"))
        registry.register(_success_adapter("algora", candidates=[_candidate("algora", "5")]))
        eng = create_discovery_engine(config=cfg, db=db)
        result = DiscoveryRuntime(registry=registry).run(config=cfg, engine=eng)
        assert result.status == RunStatus.PARTIAL
        assert result.adapters_failed == 1
        assert result.adapters_succeeded == 1
        row = db.connection.execute(
            "SELECT 1 FROM bounties WHERE source = ? AND source_id = ?",
            ("algora", "5"),
        ).fetchone()
        assert row is not None

    def test_adapter_a_success_adapter_b_failed_adjacency(
        self, tmp_dir, registry, db
    ):
        config_file = write_discovery_config(
            tmp_dir,
            """
            version: 1
            sources:
              github:
                enabled: true
              taskbounty:
                enabled: true
            """,
        )
        cfg = Config(discovery_config_path=str(config_file))
        registry.register(_success_adapter("github", candidates=[_candidate("github", "9")]))
        registry.register(_failed_adapter("taskbounty", error="taskbounty down"))
        eng = create_discovery_engine(config=cfg, db=db)
        result = DiscoveryRuntime(registry=registry).run(config=cfg, engine=eng)
        assert result.status == RunStatus.PARTIAL
        row = db.connection.execute(
            "SELECT 1 FROM bounties WHERE source = ? AND source_id = ?",
            ("github", "9"),
        ).fetchone()
        assert row is not None


# ===================================================================
# Deterministic order tests
# ===================================================================


class TestDeterministicOrder:
    def test_execution_order_stable_across_runs(self, tmp_dir, registry, db):
        config_file = write_discovery_config(
            tmp_dir,
            """
            version: 1
            sources:
              z_source:
                enabled: true
              a_source:
                enabled: true
              m_source:
                enabled: true
            """,
        )
        cfg = Config(discovery_config_path=str(config_file))

        execution_order = []

        class OrderTracker:
            def __init__(self, source: str):
                self.source = source
                self.adapter_version = ADAPTER_CONTRACT_VERSION

            def fetch(self, run_context: RunContext) -> AdapterResult:
                execution_order.append(self.source)
                return make_adapter_result(source=self.source, status=AdapterStatus.SUCCESS)

        registry.register(OrderTracker("z_source"))
        registry.register(OrderTracker("a_source"))
        registry.register(OrderTracker("m_source"))

        eng = create_discovery_engine(config=cfg, db=db)

        execution_order.clear()
        DiscoveryRuntime(registry=registry).run(config=cfg, engine=eng)
        order_1 = list(execution_order)

        execution_order.clear()
        DiscoveryRuntime(registry=registry).run(config=cfg, engine=eng)
        order_2 = list(execution_order)

        assert order_1 == order_2
        assert order_1 == ["a_source", "m_source", "z_source"]


# ===================================================================
# DiscoveryEngine integration tests
# ===================================================================


class TestDiscoveryEngineIntegration:
    def test_runtime_delegates_to_existing_engine(self, tmp_dir, registry, db):
        config_file = write_discovery_config(
            tmp_dir,
            """
            version: 1
            sources:
              github:
                enabled: true
            """,
        )
        cfg = Config(discovery_config_path=str(config_file))
        registry.register(_success_adapter("github", candidates=[_candidate("github", "99")]))

        persist_calls = []

        original = DiscoveryEngine._persist_candidate

        def tracking_persist(self, candidate):
            persist_calls.append(candidate.source_id)
            return original(self, candidate)

        try:
            DiscoveryEngine._persist_candidate = tracking_persist  # type: ignore[assignment]
            eng = create_discovery_engine(config=cfg, db=db)
            result = DiscoveryRuntime(registry=registry).run(config=cfg, engine=eng)
            assert result.status == RunStatus.SUCCESS
            assert "99" in persist_calls
        finally:
            DiscoveryEngine._persist_candidate = original  # type: ignore[assignment]

    def test_engine_limits_enforced_by_runtime(self, tmp_dir, registry, db):
        config_file = write_discovery_config(
            tmp_dir,
            """
            version: 1
            sources:
              github:
                enabled: true
            """,
        )
        cfg = Config(discovery_config_path=str(config_file))
        candidates = [
            _candidate("github", str(i), title=f"Issue {i}")
            for i in range(201)
        ]
        registry.register(_success_adapter("github", candidates=candidates))
        eng = create_discovery_engine(config=cfg, db=db)
        result = DiscoveryRuntime(registry=registry).run(config=cfg, engine=eng)
        assert result.candidates_inserted <= 200
        assert result.limit_reached is True


# ===================================================================
# No-network proof tests
# ===================================================================


class TestNoNetwork:
    def test_runtime_does_not_import_network_modules(self):
        import ast
        base = Path(__file__).resolve().parent.parent.parent
        for rel_path in [
            "hbh/discovery/runtime.py",
            "hbh/discovery/registry.py",
        ]:
            full = base / rel_path
            tree = ast.parse(full.read_text(encoding="utf-8"))
            imported_names = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imported_names.add(alias.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported_names.add(node.module.split(".")[0])
            prohibited = {"requests", "httpx", "aiohttp", "urllib", "http", "socket", "smtplib", "ftplib"}
            intersection = prohibited & imported_names
            assert not intersection, f"Network modules found in {rel_path}: {intersection}"


# ===================================================================
# Source agnosticism test
# ===================================================================


class TestSourceAgnosticism:
    def test_runtime_has_no_source_specific_branches(self):
        base = Path(__file__).resolve().parent.parent.parent
        runtime_path = base / "hbh" / "discovery" / "runtime.py"
        source = runtime_path.read_text(encoding="utf-8")
        prohibited = [
            'if source == "github"',
            'elif source == "github"',
            'if source == "algora"',
            'elif source == "algora"',
            'if source == "taskbounty"',
            'elif source == "taskbounty"',
            "github",
            "algora",
            "taskbounty",
        ]
        for pattern in prohibited:
            assert pattern not in source, f"Runtime contains prohibited pattern: {pattern!r}"


# ===================================================================
# RunContext contract preserved
# ===================================================================


class TestRunContextPreserved:
    def test_runtime_uses_runcontext_not_parallel_context(self):
        src = inspect.getsource(DiscoveryRuntime)
        assert "RunContext" in src
        assert "RuntimeContext" not in src
        assert "DiscoveryContext" not in src


# ===================================================================
# AdapterResult contract preserved
# ===================================================================


class TestAdapterResultPreserved:
    def test_runtime_returns_discoveryrunresult_via_engine(self, tmp_dir, registry, db):
        config_file = write_discovery_config(
            tmp_dir,
            """
            version: 1
            sources:
              github:
                enabled: true
            """,
        )
        cfg = Config(discovery_config_path=str(config_file))
        registry.register(_success_adapter("github", candidates=[_candidate("github", "1")]))
        eng = create_discovery_engine(config=cfg, db=db)
        result = DiscoveryRuntime(registry=registry).run(config=cfg, engine=eng)
        assert isinstance(result, DiscoveryRunResult)
