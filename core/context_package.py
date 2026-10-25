from dataclasses import dataclass, field


@dataclass
class ContextPackage:
    """
    Data contract for context passed to the future Context Engine.

    Phase 0 only defines this passive model.
    Context extraction and enrichment are intentionally deferred
    to Phase 8.
    """

    bounty_id: str = ""
    repo_id: str = ""
    files: list[str] = field(default_factory=list)
    issue_body: str = ""
    constraints: dict[str, object] = field(default_factory=dict)
