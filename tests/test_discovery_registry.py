"""
Tests for hbh.discovery.registry — Phase 1b-GH-2C.

Focused tests for the source-agnostic AdapterRegistry.
"""

from __future__ import annotations

import pytest

from hbh.discovery.models import (
    ADAPTER_CONTRACT_VERSION,
    AdapterResult,
    AdapterStatus,
    BountyCandidate,
    RunContext,
    make_bounty_candidate,
    make_run_context,
    make_adapter_result,
)


# ---------------------------------------------------------------------------
# Fake adapter helper for registry tests
# ---------------------------------------------------------------------------

def _make_fake_adapter(source: str, *, version: str = ADAPTER_CONTRACT_VERSION):
    """Build a minimal fake adapter for registry contract tests."""

    class FakeAdapter:
        adapter_version = version

        def __init__(self):
            self.source = source

        def fetch(self, run_context: RunContext) -> AdapterResult:
            return make_adapter_result(source=source)

    return FakeAdapter()


# ---------------------------------------------------------------------------
# Adapter contract validation
# ---------------------------------------------------------------------------


class TestRegistryContractValidation:
    def test_accepts_valid_adapter(self):
        registry = _make_registry()
        adapter = _make_fake_adapter("github")
        registry.register(adapter)
        assert registry.is_registered("github")
        assert registry.get("github") is adapter

    def test_rejects_none_as_adapter(self):
        registry = _make_registry()
        with pytest.raises(TypeError):
            registry.register(None)

    def test_rejects_object_without_source(self):
        registry = _make_registry()

        class BadAdapter:
            adapter_version = "1.0.0"

            def fetch(self, run_context: RunContext) -> AdapterResult:
                return make_adapter_result(source="x")

        with pytest.raises(TypeError, match="missing 'source' attribute"):
            registry.register(BadAdapter())

    def test_rejects_adapter_with_empty_source(self):
        registry = _make_registry()

        class EmptySourceAdapter:
            source = ""
            adapter_version = "1.0.0"

            def fetch(self, run_context: RunContext) -> AdapterResult:
                return make_adapter_result(source="")

        with pytest.raises(ValueError, match="Adapter.source must not be empty"):
            registry.register(EmptySourceAdapter())

    def test_rejects_adapter_with_empty_version(self):
        registry = _make_registry()

        class EmptyVersionAdapter:
            source = "github"
            adapter_version = ""

            def fetch(self, run_context: RunContext) -> AdapterResult:
                return make_adapter_result(source="github")

        with pytest.raises(ValueError, match="Adapter.adapter_version must not be empty"):
            registry.register(EmptyVersionAdapter())


# ---------------------------------------------------------------------------
# Duplicate rejection
# ---------------------------------------------------------------------------


class TestRegistryDuplicateRejection:
    def test_rejects_duplicate_source(self):
        registry = _make_registry()
        adapter_a = _make_fake_adapter("github")
        adapter_b = _make_fake_adapter("github")  # same source name
        registry.register(adapter_a)
        with pytest.raises(ValueError, match="already registered"):
            registry.register(adapter_b)

    def test_different_sources_allowed(self):
        registry = _make_registry()
        registry.register(_make_fake_adapter("github"))
        registry.register(_make_fake_adapter("algora"))
        registry.register(_make_fake_adapter("taskbounty"))
        assert registry.is_registered("github")
        assert registry.is_registered("algora")
        assert registry.is_registered("taskbounty")
        items = registry.list_registered()
        assert [src for src, _ in items] == ["github", "algora", "taskbounty"]


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


class TestRegistryLookup:
    def test_get_existing_adapter(self):
        registry = _make_registry()
        adapter = _make_fake_adapter("github")
        registry.register(adapter)
        assert registry.get("github") is adapter

    def test_get_missing_adapter_returns_none(self):
        registry = _make_registry()
        assert registry.get("github") is None
        assert not registry.is_registered("github")

    def test_is_registered_true(self):
        registry = _make_registry()
        registry.register(_make_fake_adapter("github"))
        assert registry.is_registered("github")

    def test_is_registered_false(self):
        registry = _make_registry()
        assert not registry.is_registered("github")


# ---------------------------------------------------------------------------
# Unregister
# ---------------------------------------------------------------------------


class TestRegistryUnregister:
    def test_unregister_existing(self):
        registry = _make_registry()
        registry.register(_make_fake_adapter("github"))
        assert registry.unregister("github")
        assert not registry.is_registered("github")
        assert registry.get("github") is None

    def test_unregister_missing_returns_false(self):
        registry = _make_registry()
        assert not registry.unregister("github")


# ---------------------------------------------------------------------------
# Deterministic registration/lookup order
# ---------------------------------------------------------------------------


class TestRegistryDeterministicOrder:
    def test_registration_order_preserved(self):
        registry = _make_registry()
        sources = ["z_source", "a_source", "m_source"]
        adapters = [_make_fake_adapter(s) for s in sources]
        for a in adapters:
            registry.register(a)
        items = registry.list_registered()
        assert [src for src, _ in items] == sources

    def test_lookup_is_deterministic(self):
        registry = _make_registry()
        adapter = _make_fake_adapter("github")
        registry.register(adapter)
        for _ in range(5):
            assert registry.get("github") is adapter


# ---------------------------------------------------------------------------
# No source-specific branching
# ---------------------------------------------------------------------------


class TestRegistrySourceAgnostic:
    def test_registry_has_no_source_specific_branches(self):
        """Prove the registry source code contains no source-specific branches."""
        import inspect
        from hbh.discovery.registry import AdapterRegistry
        src = inspect.getsource(AdapterRegistry)
        prohibited_patterns = [
            "if source == ",
            "elif source == ",
            'if source == "github"',
            "github",
            "algora",
            "taskbounty",
        ]
        for pattern in prohibited_patterns:
            assert pattern not in src, (
                f"Registry contains prohibited pattern: {pattern!r}"
            )


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


def _make_registry():
    from hbh.discovery.registry import AdapterRegistry
    return AdapterRegistry()
