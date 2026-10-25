"""
Tests for hbh.core.context_package.

Phase 0: only validates the passive ContextPackage contract.
"""

import sys
import os

# Ensure project root is on path for direct execution
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hbh.core.context_package import ContextPackage


def test_context_package_defaults():
    """ContextPackage dapat dibuat tanpa argument dan semua field punya safe default."""
    package = ContextPackage()

    assert package.bounty_id == ""
    assert package.repo_id == ""
    assert package.files == []
    assert package.issue_body == ""
    assert package.constraints == {}


def test_context_package_mutable_defaults_are_independent():
    """Setiap instance memiliki container masing-masing. Tidak ada shared state."""
    first = ContextPackage()
    second = ContextPackage()

    first.files.append("example.py")
    first.constraints["language"] = "python"

    assert second.files == []
    assert second.constraints == {}


def test_context_package_full_initialization():
    """ContextPackage dapat diisi data penuh sesuai contract."""
    package = ContextPackage(
        bounty_id="HB-001",
        repo_id="owner/repo",
        files=["src/main.py", "tests/test_main.py"],
        issue_body="Bug report: ...",
        constraints={"language": "python", "max_files": 10},
    )

    assert package.bounty_id == "HB-001"
    assert package.repo_id == "owner/repo"
    assert package.files == ["src/main.py", "tests/test_main.py"]
    assert package.issue_body == "Bug report: ..."
    assert package.constraints == {"language": "python", "max_files": 10}
