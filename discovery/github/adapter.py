"""
HBH GitHub Discovery Adapter — Phase 1b-GH-3B-2.

Pagination + normalization layer for GitHub Issues API.

This layer provides ONLY:
- Repository configuration parsing
- HTTP request construction (delegates to GitHubHTTPClient)
- Bounded pagination (max_pages, max_candidates)
- GitHub issue payload → BountyCandidate normalization
- AdapterResult construction

It does NOT provide:
- Raw evidence persistence (GH-3B-3)
- DiscoveryRuntime integration (GH-3B-3+)
- Policy/Triage/Profiling
- EV scoring / acceptance prediction
- Git automation
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from hbh.discovery.github.http_client import GitHubHTTPClient, GitHubHTTPResponse
from hbh.discovery.models import (
    ADAPTER_CONTRACT_VERSION,
    AdapterResult,
    AdapterStatus,
    BountyCandidate,
    RunContext,
)

SOURCE: str = "github"
ADAPTER_VERSION: str = ADAPTER_CONTRACT_VERSION

DEFAULT_MAX_PAGES: int = 10
DEFAULT_MAX_CANDIDATES: int = 50
DEFAULT_PER_PAGE: int = 30
DEFAULT_STATE: str = "open"
DEFAULT_FILTER: str = "issues"


def _validate_repository(repository: str) -> bool:
    """Validate repository identifier: owner/repository format."""
    if not repository or not isinstance(repository, str):
        return False
    # owner/repository format: alphanumeric, hyphen, dot, slash
    pattern = r"^[a-zA-Z0-9](?:[a-zA-Z0-9._-]*[a-zA-Z0-9])?/[a-zA-Z0-9](?:[a-zA-Z0-9._-]*[a-zA-Z0-9])?$"
    return bool(re.match(pattern, repository))


def _parse_repository(repository: str) -> tuple[str, str]:
    """Parse 'owner/repository' into (owner, repository)."""
    parts = repository.split("/", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid repository format: {repository!r}")
    owner, repo = parts
    if not owner or not repo:
        raise ValueError(f"Invalid repository format: {repository!r}")
    return owner, repo


@dataclass
class GitHubAdapterConfig:
    """Configuration for a single GitHub repository discovery."""

    repository: str
    """owner/repository format."""

    state: str = DEFAULT_STATE
    """Issue state filter: open, closed, all."""

    filter: str = DEFAULT_FILTER
    """GitHub filter parameter: issues, pulls."""

    labels: Optional[List[str]] = None
    """Optional label filter."""

    sort: Optional[str] = None
    """Optional sort parameter: created, updated, comments."""

    direction: Optional[str] = None
    """Optional direction: asc, desc."""

    max_pages: int = DEFAULT_MAX_PAGES
    """Maximum pages to fetch per repository."""

    max_candidates: int = DEFAULT_MAX_CANDIDATES
    """Maximum candidates to collect per repository."""

    per_page: int = DEFAULT_PER_PAGE
    """Page size for GitHub API requests."""

    def __post_init__(self) -> None:
        if not _validate_repository(self.repository):
            raise ValueError(f"Invalid repository format: {self.repository!r}")


class GitHubDiscoveryAdapter:
    """
    GitHub discovery adapter.

    Responsibilities:
    - Parse repository configuration
    - Construct GitHub API requests via GitHubHTTPClient
    - Perform bounded pagination
    - Normalize GitHub issue payloads to BountyCandidate
    - Return AdapterResult

    Does NOT:
    - Persist to SQLite
    - Store raw evidence
    - Integrate with DiscoveryRuntime
    - Apply policy/triage
    """

    source: str = SOURCE
    adapter_version: str = ADAPTER_VERSION

    def __init__(
        self,
        http_client: Optional[GitHubHTTPClient] = None,
        max_pages: int = DEFAULT_MAX_PAGES,
        max_candidates: int = DEFAULT_MAX_CANDIDATES,
        per_page: int = DEFAULT_PER_PAGE,
    ) -> None:
        """
        Initialize the GitHub discovery adapter.

        Args:
            http_client: Existing GitHubHTTPClient instance.
            max_pages: Maximum pages to fetch per repository.
            max_candidates: Maximum candidates to collect per repository.
            per_page: Page size for API requests.
        """
        self._http_client = http_client or GitHubHTTPClient()
        self._max_pages = max_pages
        self._max_candidates = max_candidates
        self._per_page = per_page

    def fetch(self, run_context: RunContext) -> AdapterResult:
        """
        Fetch candidates from configured GitHub repositories.

        Args:
            run_context: Context for this discovery run.

        Returns:
            AdapterResult with normalized candidates and status.
        """
        start_time = time.time()
        all_candidates: List[BountyCandidate] = []
        total_pages_fetched = 0
        total_candidates_fetched = 0
        rate_limit_hit = False
        errors: List[str] = []
        any_repository_succeeded = False

        source_config: Dict[str, Any] = run_context.source_config
        repositories: List[str] = source_config.get("repositories", [])

        if not repositories:
            return AdapterResult(
                source=self.source,
                adapter_version=self.adapter_version,
                status=AdapterStatus.SUCCESS,
                candidates=[],
                pages_fetched=0,
                candidates_fetched=0,
                error=None,
                rate_limit_hit=False,
                elapsed_seconds=time.time() - start_time,
            )

        for repo in repositories:
            if not _validate_repository(repo):
                errors.append(f"Invalid repository format: {repo!r}")
                continue

            try:
                config = GitHubAdapterConfig(
                    repository=repo,
                    state=source_config.get("state", DEFAULT_STATE),
                    filter=source_config.get("filter", DEFAULT_FILTER),
                    labels=source_config.get("labels"),
                    sort=source_config.get("sort"),
                    direction=source_config.get("direction"),
                    max_pages=self._max_pages,
                    max_candidates=self._max_candidates,
                    per_page=self._per_page,
                )
            except ValueError as e:
                errors.append(str(e))
                continue

            try:
                repo_candidates, pages, candidates_count, hit_rate_limit, error = self._fetch_repository(
                    config, run_context.run_id
                )
            except Exception as e:
                errors.append(f"Repository {repo!r}: {str(e)}")
                continue

            # Repository was successfully queried (pages > 0 means at least one page was fetched)
            if pages > 0:
                any_repository_succeeded = True

            if hit_rate_limit:
                rate_limit_hit = True
                # Still add candidates collected before rate limit
                all_candidates.extend(repo_candidates)
                total_pages_fetched += pages
                total_candidates_fetched += candidates_count
                break

            if error:
                errors.append(f"Repository {repo!r}: {error}")
                # Still add any candidates collected before the error
                all_candidates.extend(repo_candidates)
                total_pages_fetched += pages
                total_candidates_fetched += candidates_count
                continue  # Move to next repository

            all_candidates.extend(repo_candidates)
            total_pages_fetched += pages
            total_candidates_fetched += candidates_count

            if len(all_candidates) >= self._max_candidates:
                break

        status = self._determine_status(
            all_candidates, total_pages_fetched, errors, rate_limit_hit, any_repository_succeeded
        )

        return AdapterResult(
            source=self.source,
            adapter_version=self.adapter_version,
            status=status,
            candidates=all_candidates[: self._max_candidates],
            pages_fetched=total_pages_fetched,
            candidates_fetched=total_candidates_fetched,
            error="; ".join(errors) if errors else None,
            rate_limit_hit=rate_limit_hit,
            elapsed_seconds=time.time() - start_time,
        )

    def _fetch_repository(
        self, config: GitHubAdapterConfig, run_id: str
    ) -> tuple[List[BountyCandidate], int, int, bool, Optional[str]]:
        """
        Fetch and normalize issues for a single repository.

        Returns:
            (candidates, pages_fetched, candidates_fetched, rate_limit_hit, error)
        """
        page = 1
        candidates: List[BountyCandidate] = []
        pages_fetched = 0
        candidates_fetched = 0
        rate_limit_hit = False
        error: Optional[str] = None

        while page <= config.max_pages and len(candidates) < config.max_candidates:
            params = self._build_params(config, page)
            path = f"/repos/{config.repository}/issues"

            try:
                response = self._http_client.request(path, params)
            except Exception as e:
                return candidates, pages_fetched, candidates_fetched, False, f"HTTP request failed: {type(e).__name__}: {str(e)}"

            if response.rate_limited:
                rate_limit_hit = True
                return (
                    candidates,
                    pages_fetched,
                    candidates_fetched,
                    True,
                    "Rate limit exceeded (429)",
                )

            if not response.ok:
                if response.status_code == 404:
                    return (
                        candidates,
                        pages_fetched,
                        candidates_fetched,
                        False,
                        f"Repository not found (404): {config.repository!r}",
                    )
                elif response.status_code == 401:
                    return (
                        candidates,
                        pages_fetched,
                        candidates_fetched,
                        False,
                        "Authentication failed (401)",
                    )
                elif response.status_code == 403:
                    return (
                        candidates,
                        pages_fetched,
                        candidates_fetched,
                        False,
                        f"Forbidden (403): {config.repository!r}",
                    )
                elif response.status_code >= 500:
                    return (
                        candidates,
                        pages_fetched,
                        candidates_fetched,
                        False,
                        f"Server error ({response.status_code})",
                    )
                else:
                    return (
                        candidates,
                        pages_fetched,
                        candidates_fetched,
                        False,
                        f"HTTP error ({response.status_code})",
                    )

            try:
                issues = self._parse_response_body(response.body)
            except ValueError as e:
                return (
                    candidates,
                    pages_fetched,
                    candidates_fetched,
                    False,
                    f"Invalid response: {str(e)}",
                )

            pages_fetched += 1
            candidates_fetched += len(issues)

            if not issues:
                break  # Empty page — stop pagination

            for issue in issues:
                if len(candidates) >= config.max_candidates:
                    break

                if self._is_pull_request(issue):
                    continue

                try:
                    candidate = self._normalize_issue(issue, config.repository, run_id)
                    if candidate:
                        candidates.append(candidate)
                except Exception:
                    continue  # Skip malformed issues silently

            page += 1

        return candidates, pages_fetched, candidates_fetched, rate_limit_hit, error

    def _build_params(
        self, config: GitHubAdapterConfig, page: int
    ) -> Dict[str, str]:
        """Build query parameters for the GitHub API request."""
        params: Dict[str, str] = {
            "state": config.state,
            "filter": config.filter,
            "page": str(page),
            "per_page": str(config.per_page),
        }

        if config.labels:
            params["labels"] = ",".join(config.labels)

        if config.sort:
            params["sort"] = config.sort

        if config.direction:
            params["direction"] = config.direction

        return params

    def _parse_response_body(self, body: bytes) -> List[Dict[str, Any]]:
        """Parse and validate the response body as a JSON array."""
        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            raise ValueError(f"Malformed JSON: {str(e)}") from e

        if not isinstance(data, list):
            if isinstance(data, dict):
                raise ValueError("Response is a JSON object, expected array")
            elif isinstance(data, str):
                raise ValueError("Response is a string, expected array")
            elif isinstance(data, (int, float)):
                raise ValueError("Response is a number, expected array")
            elif data is None:
                raise ValueError("Response is null, expected array")
            else:
                raise ValueError(f"Unexpected response type: {type(data).__name__}")

        return data

    def _is_pull_request(self, issue: Dict[str, Any]) -> bool:
        """Check if an issue payload represents a pull request."""
        return issue.get("pull_request") is not None

    def _normalize_issue(
        self, issue: Dict[str, Any], repository: str, run_id: str
    ) -> Optional[BountyCandidate]:
        """
        Normalize a GitHub issue payload to BountyCandidate.

        Returns None if the issue cannot be normalized (missing required fields).
        """
        number = issue.get("number")
        if number is None:
            return None

        title = issue.get("title")
        if not title:
            return None

        html_url = issue.get("html_url")
        if not html_url:
            html_url = f"https://github.com/{repository}/issues/{number}"

        repository_url = issue.get("repository_url") or f"https://github.com/{repository}"

        body = issue.get("body")
        if body is None:
            body = ""

        state_str = issue.get("state", "open")
        if state_str == "closed":
            state = "CLOSED"
        else:
            state = "OPEN"

        created_at = issue.get("created_at")
        updated_at = issue.get("updated_at")
        last_activity = issue.get("last_activity") or updated_at or created_at

        labels_raw = issue.get("labels", [])
        labels = [lbl.get("name", "") for lbl in labels_raw if isinstance(lbl, dict)]

        comments = issue.get("comments", 0)

        return BountyCandidate(
            source=SOURCE,
            source_id=f"{repository}#{number}",
            discovery_run_id=run_id,
            canonical_issue_key=f"{repository}#{number}",
            title=title,
            description=body,
            repository_url=repository_url,
            issue_url=html_url,
            source_created_at=created_at,
            source_updated_at=updated_at,
            last_activity=last_activity,
            state=state,
            labels=labels,
            raw_payload=issue,
            adapter_version=ADAPTER_VERSION,
        )

    def _determine_status(
        self,
        candidates: List[BountyCandidate],
        pages_fetched: int,
        errors: List[str],
        rate_limit_hit: bool,
        any_repository_succeeded: bool,
    ) -> str:
        """Determine the adapter result status."""
        if rate_limit_hit:
            return AdapterStatus.PARTIAL if (candidates or any_repository_succeeded) else AdapterStatus.FAILED

        if errors:
            if any_repository_succeeded:
                return AdapterStatus.PARTIAL
            return AdapterStatus.FAILED

        return AdapterStatus.SUCCESS
