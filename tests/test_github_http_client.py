"""
Tests for hbh.discovery.github.http_client — Phase 1b-GH-3B-1.

Focused tests for the GitHub HTTP transport layer.
"""

from __future__ import annotations

import json
import os
import pytest
import urllib.error
from unittest.mock import Mock, patch

from hbh.discovery.github.http_client import (
    GitHubHTTPClient,
    GitHubHTTPResponse,
    GitHubHTTPError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    """Ensure each test starts with no GITHUB_TOKEN in environment."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    yield
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)


class _MockResponse:
    """Real class to avoid Mock quirks with context managers and headers."""
    def __init__(self, status_code, headers, body):
        self.status = status_code
        self.code = status_code
        self.headers = headers
        self._body = body
    def read(self):
        return self._body
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass


def _mock_urlopen_response(status_code, headers=None, body=b"{}"):
    """Create a mock urllib response object."""
    return _MockResponse(status_code, headers if headers is not None else {}, body)


def _make_http_error(status_code, headers, body, msg="Error"):
    """Create a real urllib.error.HTTPError with fp set for .read() support."""
    from io import BytesIO
    return urllib.error.HTTPError(
        url="https://api.github.com/foo",
        code=status_code,
        msg=msg,
        hdrs=headers,
        fp=BytesIO(body),
    )


# ---------------------------------------------------------------------------
# Authentication tests
# ---------------------------------------------------------------------------


class TestAuthentication:
    def test_token_present_authorization_header(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake_token_12345")
        client = GitHubHTTPClient()
        assert client._token == "ghp_fake_token_12345"

        headers = client._build_headers()
        assert headers["Authorization"] == "Bearer ghp_fake_token_12345"

    def test_token_absent_no_authorization_header(self):
        client = GitHubHTTPClient()
        assert client._token is None

        headers = client._build_headers()
        assert "Authorization" not in headers

    def test_anonymous_request_works(self):
        """Verify anonymous client can be constructed without token."""
        client = GitHubHTTPClient()
        assert client._token is None
        assert client.base_url == "https://api.github.com"
        assert client.timeout == 10

    def test_token_read_from_environment(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_env_token_67890")
        client = GitHubHTTPClient()
        assert client._token == "ghp_env_token_67890"


# ---------------------------------------------------------------------------
# Headers tests
# ---------------------------------------------------------------------------


class TestHeaders:
    def test_accept_header(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
        client = GitHubHTTPClient()
        headers = client._build_headers()
        assert headers["Accept"] == "application/vnd.github+json"

    def test_user_agent_header(self):
        client = GitHubHTTPClient()
        headers = client._build_headers()
        assert headers["User-Agent"] == "HBH-GitHub-Adapter/1.0.0"

    def test_no_hermes_bot_identity(self):
        client = GitHubHTTPClient()
        headers = client._build_headers()
        assert "Hermes Bot" not in headers["User-Agent"]
        assert "Hermes Agent" not in headers["User-Agent"]
        assert "AI Agent" not in headers["User-Agent"]

    def test_custom_user_agent(self):
        client = GitHubHTTPClient(user_agent="CustomTest/2.0")
        headers = client._build_headers()
        assert headers["User-Agent"] == "CustomTest/2.0"

    def test_authorization_not_in_url(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret_token_xyz")
        client = GitHubHTTPClient()
        url = client._build_url("/repos/owner/repo/issues", None)
        assert "ghp_secret_token_xyz" not in url
        assert "token=" not in url
        assert "Bearer" not in url


# ---------------------------------------------------------------------------
# Request construction tests
# ---------------------------------------------------------------------------


class TestRequestConstruction:
    def test_base_url_default(self):
        client = GitHubHTTPClient()
        assert client.base_url == "https://api.github.com"

    def test_base_url_custom(self):
        client = GitHubHTTPClient(base_url="https://api.example.com")
        assert client.base_url == "https://api.example.com"

    def test_path_construction(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_token")
        client = GitHubHTTPClient()
        url = client._build_url("/repos/owner/repo/issues", None)
        assert url == "https://api.github.com/repos/owner/repo/issues"

    def test_path_with_query_params(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_token")
        client = GitHubHTTPClient()
        url = client._build_url(
            "/repos/owner/repo/issues",
            {"state": "open", "per_page": "30"},
        )
        assert "state=open" in url
        assert "per_page=30" in url
        assert "ghp_token" not in url

    def test_path_validation_rejects_empty(self):
        client = GitHubHTTPClient()
        with pytest.raises(ValueError, match="non-empty string"):
            client._validate_path("")

    def test_path_validation_rejects_no_leading_slash(self):
        client = GitHubHTTPClient()
        with pytest.raises(ValueError, match="start with '/'"):
            client._validate_path("repos/owner/repo")

    def test_path_validation_rejects_dotdot(self):
        client = GitHubHTTPClient()
        with pytest.raises(ValueError, match=r"\.\."):
            client._validate_path("/repos/owner/../evil")

    def test_path_validation_rejects_query_char(self):
        client = GitHubHTTPClient()
        with pytest.raises(ValueError, match="['?']"):
            client._validate_path("/repos/owner?foo=bar")

    def test_path_validation_rejects_fragment(self):
        client = GitHubHTTPClient()
        with pytest.raises(ValueError, match="['#']"):
            client._validate_path("/repos/owner#fragment")

    def test_path_validation_rejects_full_url(self):
        client = GitHubHTTPClient()
        with pytest.raises(ValueError, match="path must start with '/'"):
            client._validate_path("https://evil.com/path")


# ---------------------------------------------------------------------------
# Response tests
# ---------------------------------------------------------------------------


class TestResponse:
    def test_ok_true_for_200(self):
        resp = GitHubHTTPResponse(
            status_code=200,
            headers={},
            body=b"{}",
            rate_limit_remaining=None,
            rate_limit_reset=None,
            rate_limited=False,
        )
        assert resp.ok is True

    def test_ok_false_for_404(self):
        resp = GitHubHTTPResponse(
            status_code=404,
            headers={},
            body=b"Not Found",
            rate_limit_remaining=None,
            rate_limit_reset=None,
            rate_limited=False,
        )
        assert resp.ok is False

    def test_ok_false_for_500(self):
        resp = GitHubHTTPResponse(
            status_code=500,
            headers={},
            body=b"Server Error",
            rate_limit_remaining=None,
            rate_limit_reset=None,
            rate_limited=False,
        )
        assert resp.ok is False

    def test_rate_limited_true_for_429(self):
        resp = GitHubHTTPResponse(
            status_code=429,
            headers={},
            body=b"Rate limit",
            rate_limit_remaining=None,
            rate_limit_reset=None,
            rate_limited=True,
        )
        assert resp.rate_limited is True
        assert resp.status_code == 429

    def test_rate_limited_false_for_200(self):
        resp = GitHubHTTPResponse(
            status_code=200,
            headers={},
            body=b"{}",
            rate_limit_remaining=None,
            rate_limit_reset=None,
            rate_limited=False,
        )
        assert resp.rate_limited is False

    def test_rate_limit_headers_extracted(self):
        """Verify rate limit headers are correctly set on response."""
        resp = GitHubHTTPResponse(
            status_code=200,
            headers={
                "X-RateLimit-Remaining": "42",
                "X-RateLimit-Reset": "1730000000",
            },
            body=b"{}",
            rate_limit_remaining=42,
            rate_limit_reset=1730000000,
            rate_limited=False,
        )
        assert resp.rate_limit_remaining == 42
        assert resp.rate_limit_reset == 1730000000

    def test_rate_limit_headers_missing(self):
        resp = GitHubHTTPResponse(
            status_code=200,
            headers={},
            body=b"{}",
            rate_limit_remaining=None,
            rate_limit_reset=None,
            rate_limited=False,
        )
        assert resp.rate_limit_remaining is None
        assert resp.rate_limit_reset is None

    def test_response_attributes(self):
        body = b'{"issues": []}'
        resp = GitHubHTTPResponse(
            status_code=200,
            headers={"Content-Type": "application/json"},
            body=body,
            rate_limit_remaining=59,
            rate_limit_reset=1730000000,
            rate_limited=False,
        )
        assert resp.status_code == 200
        assert resp.headers["Content-Type"] == "application/json"
        assert resp.body == body


# ---------------------------------------------------------------------------
# HTTP error response tests
# ---------------------------------------------------------------------------


class TestHTTPErrorResponses:
    def test_401_response(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_token")
        client = GitHubHTTPClient()

        with patch("urllib.request.urlopen", side_effect=_make_http_error(401, {"Content-Type": "application/json"}, b'{"message": "Bad credentials"}')):
            resp = client.request("/repos/owner/repo/issues")
        assert resp.status_code == 401
        assert resp.ok is False
        assert resp.rate_limited is False

    def test_403_response(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_token")
        client = GitHubHTTPClient()

        with patch("urllib.request.urlopen", side_effect=_make_http_error(403, {"Content-Type": "application/json"}, b'{"message": "Forbidden"}')):
            resp = client.request("/repos/owner/repo/issues")
        assert resp.status_code == 403
        assert resp.ok is False

    def test_404_response(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_token")
        client = GitHubHTTPClient()

        with patch("urllib.request.urlopen", side_effect=_make_http_error(404, {"Content-Type": "application/json"}, b'{"message": "Not Found"}')):
            resp = client.request("/repos/owner/repo/issues")
        assert resp.status_code == 404
        assert resp.ok is False

    def test_429_response(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_token")
        client = GitHubHTTPClient()

        with patch("urllib.request.urlopen", side_effect=_make_http_error(
            429,
            {"Content-Type": "application/json", "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1730000000"},
            b'{"message": "Rate limit exceeded"}',
        )):
            resp = client.request("/repos/owner/repo/issues")
        assert resp.status_code == 429
        assert resp.ok is False
        assert resp.rate_limited is True
        assert resp.rate_limit_remaining == 0
        assert resp.rate_limit_reset == 1730000000

    def test_5xx_response(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_token")
        client = GitHubHTTPClient()

        with patch("urllib.request.urlopen", side_effect=_make_http_error(500, {"Content-Type": "text/plain"}, b"Internal Server Error")):
            resp = client.request("/repos/owner/repo/issues")
        assert resp.status_code == 500
        assert resp.ok is False


# ---------------------------------------------------------------------------
# 200 success response test
# ---------------------------------------------------------------------------


class TestSuccessResponse:
    def test_200_response_success(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_token")
        client = GitHubHTTPClient()

        mock_resp = _mock_urlopen_response(200, {"Content-Type": "application/json"}, b'{"issues": []}')
        with patch("urllib.request.urlopen", return_value=mock_resp):
            resp = client.request("/repos/owner/repo/issues")
        assert resp.status_code == 200
        assert resp.ok is True
        assert resp.rate_limited is False
        assert resp.body == b'{"issues": []}'


# ---------------------------------------------------------------------------
# Network failure tests
# ---------------------------------------------------------------------------


class TestNetworkFailure:
    def test_timeout_raises_githubhttperror(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_token")
        client = GitHubHTTPClient(timeout=10)

        with patch("urllib.request.urlopen", side_effect=TimeoutError("Request timed out")):
            with pytest.raises(GitHubHTTPError):
                client.request("/repos/owner/repo/issues")

    def test_connection_error_raises_githubhttperror(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_token")
        client = GitHubHTTPClient()

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
            with pytest.raises(GitHubHTTPError):
                client.request("/repos/owner/repo/issues")

    def test_os_error_raises_githubhttperror(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_token")
        client = GitHubHTTPClient()

        with patch("urllib.request.urlopen", side_effect=OSError("Network unreachable")):
            with pytest.raises(GitHubHTTPError):
                client.request("/repos/owner/repo/issues")


# ---------------------------------------------------------------------------
# Security tests
# ---------------------------------------------------------------------------


class TestSecurity:
    def test_token_not_in_exception_message(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_super_secret_123456789")
        client = GitHubHTTPClient()

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection failed")):
            with pytest.raises(GitHubHTTPError) as exc_info:
                client.request("/repos/owner/repo/issues")

        error_msg = str(exc_info.value)
        assert "ghp_super_secret_123456789" not in error_msg
        assert "Bearer" not in error_msg

    def test_token_not_in_traceback(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret_token_abc")
        client = GitHubHTTPClient()

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection reset")):
            try:
                client.request("/repos/owner/repo/issues")
            except GitHubHTTPError as e:
                import traceback
                tb_str = "".join(traceback.format_exception_only(type(e), e))
                assert "ghp_secret_token_abc" not in tb_str

    def test_response_headers_sanitized(self, monkeypatch):
        """Response headers should not contain authorization info."""
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_token")
        client = GitHubHTTPClient()

        mock_resp = _mock_urlopen_response(
            200,
            {"Content-Type": "application/json", "X-RateLimit-Remaining": "59"},
            b'{"ok": true}',
        )
        with patch("urllib.request.urlopen", return_value=mock_resp):
            resp = client.request("/repos/owner/repo/issues")
        # Response headers should not contain request Authorization header
        assert "Authorization" not in resp.headers


# ---------------------------------------------------------------------------
# Timeout tests
# ---------------------------------------------------------------------------


class TestTimeout:
    def test_default_timeout(self):
        client = GitHubHTTPClient()
        assert client.timeout == 10

    def test_custom_timeout(self):
        client = GitHubHTTPClient(timeout=30)
        assert client.timeout == 30

    def test_timeout_injected_for_tests(self):
        client = GitHubHTTPClient(timeout=5)
        assert client.timeout == 5
