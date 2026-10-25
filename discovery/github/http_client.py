"""
HBH GitHub HTTP Client — Phase 1b-GH-3B-1.

Source-specific HTTP transport layer for GitHub API requests.

This layer provides ONLY:
- HTTP transport
- Authentication header construction
- Response parsing

It does NOT provide:
- Pagination
- Normalization
- Persistence
- Discovery Engine integration
"""

from __future__ import annotations

import os
import urllib.request
import urllib.error
import urllib.parse
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class GitHubHTTPResponse:
    """
    Structured response from a GitHub API request.

    Provides transport-level information for the future adapter.
    Does NOT include adapter-level semantics (SUCCESS/PARTIAL/FAILED).
    """

    status_code: int
    """HTTP status code (200, 401, 403, 404, 429, 500, etc.)."""

    headers: Dict[str, str]
    """Response headers (sanitized, no request headers)."""

    body: bytes
    """Raw response body bytes. Not parsed as JSON."""

    rate_limit_remaining: Optional[int] = None
    """Value of X-RateLimit-Remaining header, if present."""

    rate_limit_reset: Optional[int] = None
    """Value of X-RateLimit-Reset header (Unix timestamp), if present."""

    rate_limited: bool = False
    """True if status_code == 429 (rate limited)."""

    @property
    def ok(self) -> bool:
        """True for 2xx status codes."""
        return 200 <= self.status_code < 300

    def __post_init__(self) -> None:
        if self.rate_limited and self.status_code != 429:
            raise ValueError("rate_limited=True requires status_code=429")


class GitHubHTTPError(Exception):
    """
    Raised for transport-level failures.

    Covers:
    - Network errors
    - Connection failures
    - Timeouts
    - OS-level errors

    Does NOT cover HTTP error responses (4xx, 5xx) — those are returned
    as GitHubHTTPResponse with the appropriate status_code.
    """

    pass


class GitHubHTTPClient:
    """
    GitHub API HTTP client.

    Responsibilities:
    - Construct safe GitHub API requests
    - Add authentication header when GITHUB_TOKEN is available
    - Perform HTTP requests with timeout
    - Parse responses into structured GitHubHTTPResponse

    Does NOT provide:
    - Pagination
    - Normalization
    - Persistence
    - Discovery Engine integration
    """

    def __init__(
        self,
        base_url: str = "https://api.github.com",
        timeout: int = 10,
        user_agent: str = "HBH-GitHub-Adapter/1.0.0",
    ) -> None:
        """
        Initialize the GitHub HTTP client.

        Args:
            base_url: GitHub API base URL (default: https://api.github.com).
            timeout: Request timeout in seconds (default: 10).
            user_agent: User-Agent header value (default: HBH-GitHub-Adapter/1.0.0).
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.user_agent = user_agent
        self._token: Optional[str] = os.environ.get("GITHUB_TOKEN")

    def request(
        self,
        path: str,
        params: Optional[Dict[str, str]] = None,
    ) -> GitHubHTTPResponse:
        """
        Perform a GET request to the GitHub API.

        Args:
            path: API path (e.g., "/repos/owner/repo/issues").
            params: Optional query parameters.

        Returns:
            GitHubHTTPResponse with status, headers, body, and rate limit info.

        Raises:
            GitHubHTTPError: On network error, timeout, or connection failure.
            ValueError: On invalid path.
        """
        self._validate_path(path)
        url = self._build_url(path, params)
        headers = self._build_headers()

        req = urllib.request.Request(url, headers=headers, method="GET")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return self._parse_response(response)
        except urllib.error.HTTPError as e:
            return self._parse_response(e)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise GitHubHTTPError(self._sanitize_error(e)) from e

    def _build_url(self, path: str, params: Optional[Dict[str, str]]) -> str:
        url = urllib.parse.urljoin(self.base_url, path)
        if params:
            query_string = urllib.parse.urlencode(params)
            url = f"{url}?{query_string}"
        return url

    def _build_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "Accept": "application/vnd.github+json",
            "User-Agent": self.user_agent,
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _validate_path(self, path: str) -> None:
        if not isinstance(path, str) or not path:
            raise ValueError("path must be a non-empty string")
        if not path.startswith("/"):
            raise ValueError(f"path must start with '/': {path!r}")
        if ".." in path:
            raise ValueError(f"path contains '..': {path!r}")
        if "?" in path or "#" in path:
            raise ValueError(f"path contains '?' or '#': {path!r}")
        if "://" in path:
            raise ValueError(f"path appears to be a full URL: {path!r}")
        if "\x00" in path:
            raise ValueError("path contains null byte")

    def _parse_response(self, response: Any) -> GitHubHTTPResponse:
        status_code = getattr(response, "code", getattr(response, "status", 0))
        headers: Dict[str, str] = {}
        for key, value in response.headers.items():
            headers[key] = value

        body = response.read()

        rate_limit_remaining: Optional[int] = None
        rate_limit_reset: Optional[int] = None

        if "X-RateLimit-Remaining" in headers:
            try:
                rate_limit_remaining = int(headers["X-RateLimit-Remaining"])
            except (ValueError, TypeError):
                pass

        if "X-RateLimit-Reset" in headers:
            try:
                rate_limit_reset = int(headers["X-RateLimit-Reset"])
            except (ValueError, TypeError):
                pass

        return GitHubHTTPResponse(
            status_code=status_code,
            headers=headers,
            body=body,
            rate_limit_remaining=rate_limit_remaining,
            rate_limit_reset=rate_limit_reset,
            rate_limited=(status_code == 429),
        )

    @staticmethod
    def _sanitize_error(error: Exception) -> str:
        message = str(error)
        if len(message) > 200:
            message = message[:200] + "..."
        return f"Request failed: {message}"
