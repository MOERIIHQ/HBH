# HBH GH-3A — GitHub Discovery Adapter Specification & Contract Review

**Phase:** 1b-GH-3A (Specification Only)  
**Status:** Specification Draft  
**Date:** 2026-09-26  
**Author:** Hermes Agent (executor/development agent)  
**Human review required before GH-3B implementation**

---

## 1. PURPOSE AND SCOPE

This document defines the frozen specification for **GH-3B — GitHub Discovery Adapter**.

GH-3A is **specification and contract review only**. No production adapter code is created in this phase. No real GitHub API requests are made.

The purpose of GH-3B is to implement the first real external-source adapter for HBH: a **GitHub Issues API collector + normalizer** that feeds discovered candidates into the existing discovery pipeline defined by GH-1/GH-2A/GH-2B/GH-2C.

**GH-3B is NOT:**

- Policy Engine
- Triage Engine
- Repository Profiler
- Context Engine
- Implementation Engine
- Validation Engine
- Safety Engine
- Task Selector
- EV Calculator
- Acceptance Predictor
- Hermes Executor
- Git Automation
- PR Automation

**GH-3B answers only:**

> "What GitHub issues were discovered, and what was the source evidence?"

**GH-3B must NOT answer:**

> "Which issue should HBH work on?"

---

## 2. EXISTING CONTRACTS REVIEWED

The following existing HBH contracts were inspected and are the authoritative basis for GH-3B:

### 2.1 BountyCandidate (hbh/discovery/models.py)

Frozen dataclass fields:

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| source | str | Adapter | `"github"` |
| source_id | str | Adapter | Stable identity per source |
| discovery_run_id | str | Engine | Run that produced this candidate |
| canonical_issue_key | str \| None | Adapter | Human-readable key (e.g., `owner/repo#123`) |
| title | str \| None | Adapter | Issue title |
| description | str \| None | Adapter | Issue body |
| repository_url | str \| None | Adapter | Repository URL |
| issue_url | str \| None | Adapter | Direct issue URL |
| reward | str \| None | Adapter | NULL for GitHub (no bounty field) |
| currency | str \| None | Adapter | NULL for GitHub |
| source_created_at | str \| None | Adapter | ISO-8601 created timestamp |
| source_updated_at | str \| None | Adapter | ISO-8601 updated timestamp |
| last_activity | str \| None | Adapter | Most recent activity timestamp |
| state | str \| None | Adapter | `"open"` / `"closed"` |
| labels | list[str] | Adapter | GitHub label names |
| raw_payload_reference | str \| None | Engine | Set by engine after persistence |
| raw_payload_hash | str \| None | Engine | Set by engine after persistence |
| raw_payload | dict[str, Any] \| None | Adapter | Raw source payload, NOT persisted to SQLite |
| adapter_version | str | Adapter | `ADAPTER_CONTRACT_VERSION = "1.0.0"` |

Validation (engine._validate_candidate):
- source non-empty
- source_id non-empty
- discovery_run_id non-empty
- adapter_version non-empty
- title non-empty
- At least one of issue_url or repository_url present and valid URL

### 2.2 AdapterResult (hbh/discovery/models.py)

| Field | Type | Description |
|-------|------|-------------|
| source | str | Source identifier |
| adapter_version | str | Adapter version |
| status | str | SUCCESS / PARTIAL / FAILED |
| candidates | list[BountyCandidate] | Empty when FAILED |
| pages_fetched | int | Pages actually fetched |
| candidates_fetched | int | Raw candidates before normalization/dedup |
| error | str \| None | Human-readable error summary |
| rate_limit_hit | bool | Rate limit encountered |
| elapsed_seconds | float | Wall-clock fetch time |

### 2.3 DiscoveryAdapter Protocol (hbh/discovery/models.py)

```python
class DiscoveryAdapter(Protocol):
    source: str
    adapter_version: str
    def fetch(self, run_context: RunContext) -> AdapterResult: ...
```

### 2.4 RunContext (hbh/discovery/models.py)

| Field | Type | Description |
|-------|------|-------------|
| run_id | str | Unique discovery run ID |
| started_at | datetime | Run start timestamp |
| discovery_query | str | Source-specific query string |
| source_config | dict[str, Any] | Per-source configuration dict |

The GitHub adapter reads its configuration from `run_context.source_config["github"]`.

### 2.5 Discovery Engine (hbh/discovery/engine.py)

Key behaviors GH-3B must respect:

- **MAX_TOTAL_CANDIDATES = 200** — hard engine ceiling
- **MAX_RUN_DURATION_SECONDS = 300** — hard engine ceiling
- Candidate validation: source/identity/URL checks
- Deduplication: `(source, source_id)` via SQLite
- Raw evidence: stored by engine via `RawStorage.store(source, raw_payload)`
- Failure isolation: adapter exceptions caught and converted to FAILED result
- Status aggregation: SUCCESS/PARTIAL/FAILED based on adapter results

### 2.6 Raw Evidence Storage (hbh/discovery/raw_storage.py)

- Path: `<raw_root>/<source>/<sha256>.json`
- Canonicalization: UTF-8 JSON, `sort_keys=True`, `separators=(",",":")`, `ensure_ascii=False`
- SHA-256 of canonical bytes = filename + stored hash
- Duplicate content: no rewrite
- Integrity conflict: `EvidenceIntegrityError`, never silent overwrite
- Path safety: source must match `^[a-zA-Z][a-zA-Z0-9_.-]*$`, reject `../`, `/`, `\`, `~`
- **Non-JSON-serializable objects raise TypeError** (no `default=str` fallback)

### 2.7 Database (hbh/core/database.py)

`bounties` table discovery columns:
- source TEXT
- source_id TEXT
- canonical_issue_key TEXT
- repository_url TEXT
- issue_url TEXT
- currency TEXT
- source_created_at TEXT
- source_updated_at TEXT
- last_activity TEXT
- state TEXT
- labels TEXT (JSON-encoded list)
- raw_payload_reference TEXT
- raw_payload_hash TEXT
- adapter_version TEXT
- discovery_run_id TEXT

Deduplication: unique on `(source, source_id)` via `idx_bounties_source_source_id`.

### 2.8 Configuration (hbh/core/config.py + config/discovery_config.yaml)

`Config` fields relevant to GitHub adapter:
- `discovery_config_path` — path to discovery_config.yaml
- `raw_storage_path` — path to raw evidence storage (may be None)
- `hbhome` — base directory

`discovery_config.yaml` shape:
```yaml
version: 1
sources:
  github:
    enabled: true
    repositories:
      - owner/repository
limits:
  github:
    max_pages: 10
    max_candidates: 50
```

GitHub adapter reads:
- `run_context.source_config["github"]["repositories"]` — list of `"owner/repo"` strings
- `run_context.source_config["github"].get("max_pages")` — adapter-level page limit
- `run_context.source_config["github"].get("max_candidates")` — adapter-level candidate limit
- `run_context.source_config["github"].get("state")` — optional issue state filter
- `run_context.source_config["github"].get("labels")` — optional label filter
- `run_context.source_config["github"].get("sort")` — optional sort parameter
- `run_context.source_config["github"].get("direction")` — optional sort direction
- `run_context.source_config["github"].get("since")` — optional since timestamp

### 2.9 Discovery Runtime (hbh/discovery/runtime.py)

- Loads `DiscoveryConfig`
- Collects enabled sources in **deterministic sorted order**
- Resolves adapters via `AdapterRegistry`
- Raises `RuntimeError` if enabled source has no registered adapter
- Builds per-source `source_config` dict
- Delegates to existing `DiscoveryEngine`

GH-3B GitHub adapter is registered as `source="github"` in the registry.

### 2.10 GH-2C Frozen Semantics

- **SUCCESS + 0 candidates** is valid SUCCESS, not failure
- **PARTIAL** = some adapters succeeded, some failed
- **FAILED** = all adapters failed or no enabled adapters
- Disabled sources not treated as failures
- Missing adapter on enabled source = explicit error

---

## 3. GITHUB API CONTRACT

### 3.1 Endpoint

```
GET https://api.github.com/repos/{owner}/{repo}/issues
```

This is the established endpoint from Phase 1a reconnaissance. No other GitHub endpoints are authorized for GH-3B.

### 3.2 Required Parameters

| Parameter | Value | Notes |
|-----------|-------|-------|
| `state` | `"open"` (default) | Can be configured; `"all"` includes closed |
| `filter` | `"issues"` (default) | Excludes pull requests by default; see Section 8 |

The GitHub Issues API with `filter=issues` returns only issues, not pull requests. This is the default and recommended mode for GH-3B.

### 3.3 Optional Query Parameters (from configuration)

| Parameter | Source | Notes |
|-----------|--------|-------|
| `labels` | config | Comma-separated label filter (e.g., `"bug,good first issue"`) |
| `sort` | config | `"created"`, `"updated"`, `"comments"` |
| `direction` | config | `"asc"` or `"desc"` |
| `since` | config | ISO-8601 timestamp; issues updated after this time |
| `per_page` | config or default 30 | GitHub max is 100 |
| `page` | internal | Pagination cursor, starting at 1 |

### 3.4 Unresolved Questions

- **Rate limit headers:** `X-RateLimit-Remaining`, `X-RateLimit-Reset`, `X-RateLimit-Limit` are documented by GitHub. GH-3B should read these but the exact behavior on rate limit exhaustion needs human confirmation (sleep until reset, or fail with PARTIAL?).
- **Anonymous vs authenticated:** Without `GITHUB_TOKEN`, the API allows 60 requests/hour. With token, 5000 requests/hour. GH-3B should support both modes but anonymous mode severely limits pagination.

---

## 4. NORMALIZATION CONTRACT

### 4.1 GitHub Issue JSON → BountyCandidate Mapping

Given a GitHub issue object from the API response:

```json
{
  "number": 123,
  "title": "Fix null pointer in checkout",
  "body": "Step-by-step reproduction...",
  "state": "open",
  "labels": [{"name": "bug"}, {"name": "good first issue"}],
  "created_at": "2026-01-15T10:00:00Z",
  "updated_at": "2026-09-20T15:30:00Z",
  "closed_at": null,
  "user": {"login": "octocat"},
  "html_url": "https://github.com/owner/repo/issues/123",
  "repository_url": "https://api.github.com/repos/owner/repo",
  "comments": 4,
  "assignee": null,
  "milestone": null,
  "pull_request": null
}
```

The GH-3B adapter produces:

| BountyCandidate Field | GitHub Source | Transformation |
|----------------------|---------------|----------------|
| source | constant | `"github"` |
| source_id | `number` | `"owner/repo#123"` or `"123"` — **TBD: human decides format** |
| discovery_run_id | RunContext.run_id | Passed through |
| canonical_issue_key | computed | `f"{owner}/{repo}#{number}"` |
| title | `title` | Direct string |
| description | `body` | Direct string (may be null → empty string or None) |
| repository_url | `repository_url` | Convert API URL → `https://github.com/{owner}/{repo}` |
| issue_url | `html_url` | Direct URL |
| reward | — | **NULL** (GitHub has no bounty field) |
| currency | — | **NULL** |
| source_created_at | `created_at` | ISO-8601 string |
| source_updated_at | `updated_at` | ISO-8601 string |
| last_activity | `updated_at` | Use `updated_at` as proxy for last activity |
| state | `state` | `"open"` or `"closed"` |
| labels | `labels[].name` | Extract label names into list of strings |
| adapter_version | constant | `ADAPTER_CONTRACT_VERSION` |
| raw_payload | full issue object | The complete GitHub API response for this issue (see Section 5) |

### 4.2 Source Facts vs Derived Judgments

**Source facts (adapter produces these):**

- `number`, `title`, `body`, `state`, `labels`, `created_at`, `updated_at`, `html_url`, `repository_url`, `user`, `comments`, `assignee`, `milestone`

**Derived judgments (adapter must NOT produce):**

- `difficulty` — not in GitHub data
- `priority` — not in GitHub data
- `ev` / `expected_value` — not in GitHub data
- `acceptance_probability` — not in GitHub data
- `complexity` — not in GitHub data
- `competition` — not in GitHub data
- `feasibility` — not in GitHub data
- "good bounty" / "bad bounty" classification — policy decision
- "should work on this" — task selection decision

### 4.3 Canonical Issue Key

The specification proposes:

```
canonical_issue_key = f"{owner}/{repo}#{number}"
```

This matches the Phase 1a reconnaissance convention. Human review required to confirm this is the desired canonical key format.

### 4.4 source_id Format

Two options for `source_id`:

- **Option A:** `"owner/repo#123"` — includes repository context, unique across HBH
- **Option B:** `"123"` — issue number only, unique only within a single repository

The specification **prefers Option A** because HBH's deduplication is `(source, source_id)`, and source is always `"github"`. Without repository context in `source_id`, two issues with the same number in different repositories would collide.

Human review required to confirm `source_id` format.

---

## 5. RAW EVIDENCE CONTRACT

### 5.1 What Is Stored

For each GitHub issue, the adapter constructs `raw_payload` as the **complete GitHub API response object** for that issue — exactly as received from the API, not reconstructed from BountyCandidate.

The raw payload includes all fields GitHub returns, including fields not mapped to BountyCandidate:

- `number`, `title`, `body`, `state`, `labels`, `created_at`, `updated_at`, `closed_at`, `user`, `html_url`, `repository_url`, `comments`, `assignee`, `milestone`, `pull_request`, `reactions`, `timeline_url`, `comments_url`, `events_url`, `html_url`, etc.

### 5.2 What Is NOT Stored in Raw Evidence

- HTTP headers (especially `Authorization`, `Authorization` tokens)
- `GITHUB_TOKEN` value
- Any credential material
- HTTP request metadata beyond the response body

The raw payload is the **JSON response body only**.

### 5.3 Provenance Chain

```
GitHub API Response (JSON body)
        ↓
raw_payload = full issue object
        ↓
BountyCandidate(raw_payload=raw_payload, ...)
        ↓
DiscoveryEngine._persist_candidate(candidate)
        ↓
RawStorage.store("github", candidate.raw_payload)
        ↓
<raw_root>/github/<sha256>.json  (canonical JSON, SHA-256 filename)
        ↓
raw_payload_reference = "github/<sha256>.json"
raw_payload_hash = "<sha256>"
        ↓
SQLite bounties table (reference + hash, NOT raw payload)
```

### 5.4 SHA-256 Integrity

The hash is computed by `RawStorage._canonicalize()`:
1. JSON-serialize `raw_payload` with `sort_keys=True`, `separators=(",",":")`, `ensure_ascii=False`
2. UTF-8 encode
3. SHA-256 of bytes

The same hash is used as the filename and stored in `raw_payload_hash`.

### 5.5 Deduplication of Raw Evidence

If the same GitHub issue payload is encountered in a later run:
- Same canonical bytes → same SHA-256 → same file path
- `RawStorage.store()` detects existing file with matching hash → returns without rewriting
- No integrity conflict

If different payload for same issue (e.g., issue was updated between runs):
- Different canonical bytes → different SHA-256 → different file path
- New evidence file created alongside old one
- New candidate with new `raw_payload_reference` / `raw_payload_hash`

---

## 6. ERROR / RATE LIMIT CONTRACT

### 6.1 HTTP Status Handling

| Status | Adapter Behavior | AdapterResult Status |
|--------|-----------------|---------------------|
| 200 | Parse issues, normalize, continue pagination | SUCCESS or PARTIAL |
| 401 | Unauthorized — token invalid or missing | FAILED (if no candidates fetched) or PARTIAL (if some fetched before 401) |
| 403 | Forbidden — token lacks scope or repo access denied | FAILED or PARTIAL |
| 404 | Repository not found | FAILED for that repository; other repositories still attempted |
| 429 | Rate limited — check `X-RateLimit-Remaining` | PARTIAL (if some candidates fetched) or FAILED |
| 5xx | Server error — transient | PARTIAL (if some candidates fetched) or FAILED |
| Network timeout | Connection timeout | PARTIAL or FAILED |
| Connection failure | DNS/connection error | PARTIAL or FAILED |
| Malformed JSON | Response not valid JSON | FAILED |
| Unexpected payload structure | Missing required fields | FAILED for that issue; other issues still processed |

### 6.2 AdapterResult Status Semantics

- **SUCCESS:** All configured repositories processed successfully, all candidates fetched, no errors. May return 0 candidates (empty repository) — still SUCCESS.
- **PARTIAL:** At least one repository/candidate succeeded, but some errors occurred (rate limit, some 5xx, some 404, etc.).
- **FAILED:** No candidates could be fetched from any repository. All repositories failed.

### 6.3 Rate Limit Behavior

When `X-RateLimit-Remaining` reaches 0:
- GH-3B should stop fetching and return PARTIAL or FAILED
- Should NOT retry immediately (no retry logic in GH-3B — deferred to later phase)
- `rate_limit_hit = True` in AdapterResult

Exact behavior on 429 (retry-after vs immediate failure) is **unresolved** — human review required.

### 6.4 Repository-Level Isolation

Errors on one repository must NOT prevent fetching from other configured repositories. Each repository is fetched independently. If repository A returns 404 and repository B returns 200 with candidates, the result is PARTIAL with candidates from B.

---

## 7. AUTHENTICATION CONTRACT

### 7.1 Token Source

```
GITHUB_TOKEN environment variable
```

The adapter reads `os.environ.get("GITHUB_TOKEN")`.

### 7.2 Authentication Modes

**Authenticated mode:** `GITHUB_TOKEN` is set and non-empty.
- Include header: `Authorization: Bearer <token>`
- Higher rate limit (5000 requests/hour)
- Access to private repositories if token has scope

**Anonymous mode:** `GITHUB_TOKEN` is unset, empty, or None.
- No Authorization header
- Lower rate limit (60 requests/hour)
- Public repositories only
- Severely limits pagination for active repositories

### 7.3 Behavior When Token Is Absent

- Adapter operates in anonymous mode
- Logs/info event that token is absent (no token value in log)
- Continues discovery with rate limit constraints
- Returns SUCCESS/PARTIAL/FAILED based on results

### 7.4 Behavior When Token Is Invalid

- API returns 401 for requests
- Adapter detects 401 and returns FAILED or PARTIAL
- Error message in AdapterResult.error describes authentication failure without including token value

### 7.5 Secret Boundary — MANDATORY

The `GITHUB_TOKEN` must NEVER appear in:

- SQLite database (any column)
- Raw evidence files (`<raw_root>/github/<sha256>.json`)
- Audit/log events
- AdapterResult.error text
- BountyCandidate fields
- Exception messages
- Console output
- Any file written by HBH

The token is read from environment, used to construct the HTTP Authorization header, and then discarded. It is never stored, logged, or included in any data structure.

### 7.6 No Alternative Credential Storage

GH-3B does NOT create:
- Credential files
- Token caches
- Encrypted token storage
- `~/.hbh/credentials` or similar

If credential persistence is needed in a future phase, it must be designed explicitly with security review. GH-3B reads from environment only.

---

## 8. ISSUE VS PULL REQUEST HANDLING

### 8.1 Detection

GitHub's Issues API returns both issues and pull requests in the same response. Each object has a `pull_request` field:

- **Issue:** `pull_request` is `null` (absent or null)
- **Pull Request:** `pull_request` is an object with `url`, `html_url`, `diff_url`, `patch_url`

### 8.2 GH-3B Default Behavior — Issues Only

GH-3B **excludes pull requests from primary bounty candidates**.

Rationale:
- Bounty hunting targets issues (bugs, features, tasks), not pull requests
- Pull requests represent ongoing work, not discovery targets
- GH-1/GH-2 semantics are issue-centric
- Mixing PRs into the candidate pool would conflate two different concepts

When `pull_request` field is present and non-null on an API response object, GH-3B skips that object as a candidate.

### 8.3 Raw Evidence for PRs

Even though PRs are excluded from candidates, GH-3B must still preserve raw evidence when appropriate. Two approaches:

**Approach A (preferred):** Do not fetch PRs at all. Use `filter=issues` parameter to exclude PRs at the API level. Raw evidence contains only issues.

**Approach B:** Fetch all objects, filter PRs from candidates, but still store raw evidence for PRs if they appear in the response. This preserves the evidence but produces no candidate.

**Recommendation:** Approach A is simpler and cleaner. GH-3B uses `filter=issues` by default. If future phases need PR data, a separate PR-specific adapter or parameter can be added.

### 8.4 Deterministic Behavior

PR exclusion is deterministic:
- Same API response → same filtering → same candidates
- No PR becomes a candidate in GH-3B
- No candidate is silently converted from PR to issue

### 8.5 Configuration for PR Inclusion (Future)

If a future phase requires PR discovery, the configuration can add:

```yaml
sources:
  github:
    enabled: true
    repositories:
      - owner/repo
    include_pull_requests: false  # default; future: true
```

GH-3B does not implement this. It is documented as a future extension point.

---

## 9. PAGINATION

### 9.1 Pagination Parameters

| Parameter | Value |
|-----------|-------|
| `page` | Starting at 1, incrementing by 1 |
| `per_page` | Configurable, default 30, GitHub max 100 |

### 9.2 Stopping Conditions

Pagination stops when ANY of:

1. **Empty page:** API returns empty array `[]` — no more results
2. **Max pages reached:** `page > config.max_pages` (or default 10)
3. **Max candidates reached:** `candidates_fetched >= config.max_candidates` (or default 50)
4. **Global engine limit:** Discovery Engine's `MAX_TOTAL_CANDIDATES = 200` is approaching — adapter should stop producing candidates when engine indicates limit (or adapter enforces its own lower limit)
5. **Unrecoverable error:** 401, 403, 429, 5xx that cannot be recovered from

### 9.3 Adapter-Level Limits

From `discovery_config.yaml`:

```yaml
limits:
  github:
    max_pages: 10        # Per-repository page limit
    max_candidates: 50   # Per-repository candidate limit
```

GH-3B enforces these as source-local safety limits. They must be **lower than or equal to** the engine's global limits (200 candidates, 300 seconds).

### 9.4 No Unbounded Pagination

GH-3B must NOT:
- Fetch all pages until rate limit exhaustion
- Fetch indefinitely
- Ignore `max_pages` or `max_candidates` configuration

### 9.5 Engine Limit Interaction

The Discovery Engine enforces `MAX_TOTAL_CANDIDATES = 200`. GH-3B should be aware of this but does NOT duplicate the limit logic. The adapter tracks `candidates_fetched` and stops when its own `max_candidates` is reached. The engine independently stops accepting candidates when 200 is reached.

If the adapter produces more candidates than the engine can accept, the excess are rejected by the engine (counted as duplicates or limit-reached). The adapter's `candidates_fetched` counts all fetched candidates, while `candidates_inserted` is tracked by the engine.

### 9.6 Page Order

Pages are fetched in order: 1, 2, 3, ... N. GitHub's pagination is offset-based (not cursor-based), so page N+1 follows page N deterministically.

---

## 10. CONFIGURATION STRUCTURE

### 10.1 discovery_config.yaml — GitHub Section

```yaml
version: 1

sources:
  github:
    enabled: true
    repositories:
      - octocat/Hello-World
      - owner/another-repo
    # Optional per-source parameters
    state: open           # "open" (default), "closed", or "all"
    labels: ""            # Comma-separated label filter, empty = no filter
    sort: created         # "created" (default), "updated", "comments"
    direction: desc       # "desc" (default), "asc"
    since: ""             # ISO-8601 timestamp, empty = no filter
    max_pages: 10         # Per-repository page limit
    max_candidates: 50    # Per-repository candidate limit
    per_page: 30          # Per-page result count (GitHub max 100)
```

### 10.2 Mandatory Fields

- `enabled` — boolean, required (default false)
- `repositories` — list of `"owner/repo"` strings, required if enabled

### 10.3 Optional Fields

All other fields are optional with documented defaults.

### 10.4 No New Environment Variables

GH-3B does NOT introduce:
- `HBH_DISCOVERY_REPOS`
- `HBH_GITHUB_REPOS`
- Any new env var for repository configuration

Repository configuration remains in `discovery_config.yaml`, read via the existing `Config.discovery_config_path` mechanism.

### 10.5 Repository Format

Each repository is a string `"owner/repository"`. The adapter parses this into `owner` and `repo` components for API URL construction.

Invalid formats (no `/`, empty owner, empty repo) are rejected at configuration load time, not at API call time.

---

## 11. SECURITY BOUNDARY — DATA VS INSTRUCTION

### 11.1 Invarant

**GitHub issue content is UNTRUSTED EXTERNAL DATA.**

Issue title, body, comments, labels, and all other GitHub-provided fields must NEVER be treated as system instructions, prompts, or commands to any component of HBH.

### 11.2 What This Means

- GitHub issue body is stored as a string field in `BountyCandidate.description`
- GitHub issue body is stored as a JSON value in raw evidence
- GitHub issue body is NEVER passed to Hermes, an LLM, or any instruction-processing component
- GitHub issue body is NEVER interpreted as a command, query, or instruction
- GitHub issue body is displayed only in contexts that treat it as data (UI, reports, logs as data)

### 11.3 Future Context Engine Boundary

Later phases (Context Engine / GH-? ) may need to analyze issue content for relevance, similarity, or other data operations. When that happens:

- The trust boundary must be explicitly designed
- Issue content must be marked as untrusted data
- Any processing of issue content must be data-processing, not instruction-execution
- No direct injection of issue content into system prompts without explicit sanitization and trust design

### 11.4 GH-3B Responsibility

GH-3B's responsibility is limited to:
- Fetching issue data from GitHub API
- Normalizing it into BountyCandidate
- Storing raw evidence

GH-3B must NOT:
- Send issue content to any LLM/Hermes component
- Interpret issue content as instructions
- Execute any code derived from issue content

This is a **spec-level security invariant** that GH-3B implementation must preserve.

---

## 12. SOURCE-SPECIFIC LOGIC BOUNDARY

### 12.1 Allowed in GitHub Adapter

- GitHub API URL construction (`https://api.github.com/repos/{owner}/{repo}/issues`)
- GitHub query parameter handling (`state`, `labels`, `sort`, `direction`, `since`, `per_page`, `page`)
- GitHub authentication (`Authorization: Bearer <token>`)
- GitHub response parsing (JSON deserialization)
- GitHub issue → BountyCandidate normalization (field mapping)
- GitHub pull request detection (`pull_request` field check)
- GitHub rate limit header reading (`X-RateLimit-Remaining`, etc.)
- GitHub error status interpretation (401, 403, 404, 429, 5xx)

### 12.2 NOT Allowed in GitHub Adapter

- Any logic that belongs to Policy Engine (scoring, ranking, selection)
- Any logic that belongs to Triage Engine (complexity, feasibility, competition analysis)
- Any logic that belongs to Repository Profiler (repository metadata, language analysis)
- Any logic that belongs to Context Engine (cross-source correlation, semantic analysis)
- Any logic that belongs to Implementation Engine (code generation, patch creation)
- Any logic that belongs to Validation Engine (code validation, test execution)
- Any logic that belongs to Safety Engine (security scanning, vulnerability assessment)
- Task selection or recommendation logic
- EV calculation or acceptance prediction

### 12.3 NOT Allowed to Leak Into Generic Components

The following must NOT contain GitHub-specific logic:

- `DiscoveryEngine` (hbh/discovery/engine.py)
- `DiscoveryRuntime` (hbh/discovery/runtime.py)
- `AdapterRegistry` (hbh/discovery/registry.py)
- `RawStorage` (hbh/discovery/raw_storage.py)
- `BountyCandidate` (hbh/discovery/models.py)
- `RunContext` (hbh/discovery/models.py)
- `AdapterResult` (hbh/discovery/models.py)
- `Config` (hbh/core/config.py)
- `Database` (hbh/core/database.py)

### 12.4 Runtime Source Agnosticism

After GH-3B, the runtime must continue to operate without knowing about GitHub as a special case:

```python
# DiscoveryRuntime does NOT contain:
if source == "github":
    # GitHub-specific logic
elif source == "algora":
    # Algora-specific logic
```

The runtime treats `"github"` as just another source string. All GitHub-specific behavior is inside the GitHub adapter.

---

## 13. OBSERVABILITY CONTRACT

### 13.1 AdapterResult Fields to Populate

GH-3B GitHub adapter populates:

| Field | Value |
|-------|-------|
| source | `"github"` |
| adapter_version | `ADAPTER_CONTRACT_VERSION` (`"1.0.0"`) |
| status | `SUCCESS`, `PARTIAL`, or `FAILED` |
| candidates | List of `BountyCandidate` (empty if FAILED) |
| pages_fetched | Number of pages actually fetched across all repositories |
| candidates_fetched | Number of raw issues fetched before normalization/dedup |
| error | Human-readable error summary (NULL on SUCCESS) |
| rate_limit_hit | `True` if any rate limit encountered |
| elapsed_seconds | Wall-clock time for entire fetch |

### 13.2 Audit/Log Events

The adapter should not emit its own audit events directly. Audit events are emitted by:
- `DiscoveryEngine` — run lifecycle, candidate ingestion, rejections, duplicates
- `DiscoveryRuntime` — missing adapter detection

The adapter may log internal operational messages (via Python `logging` or HBH's `log_info`/`log_warn`) but must not expose secrets.

### 13.3 What to Log

- Repository being fetched (owner/repo)
- Page being fetched (page number)
- Number of candidates found per repository
- Rate limit remaining (numeric value, not token)
- Error status codes (401, 404, 429, 5xx) without token or credentials
- Total elapsed time

### 13.4 What NOT to Log

- `GITHUB_TOKEN` value (ever)
- Authorization headers
- Full request URLs with credentials
- Response bodies containing sensitive data
- Private repository names if token reveals access (operational decision — human review may be needed)

---

## 14. TEST PLAN — GH-3B

### 14.1 Normalization Tests

| Test | Description |
|------|-------------|
| test_valid_issue_normalizes | Valid GitHub issue JSON → valid BountyCandidate with all fields mapped correctly |
| test_source_id_format | `source_id` uses `owner/repo#number` format (or confirm alternative) |
| test_repository_url_converted | API URL `https://api.github.com/repos/owner/repo` → `https://github.com/owner/repo` |
| test_issue_url_from_html_url | `issue_url` set to `html_url` from GitHub response |
| test_timestamps_preserved | `created_at`, `updated_at`, `last_activity` preserved as ISO-8601 strings |
| test_labels_extracted | Label names extracted from `labels[].name` into list of strings |
| test_reward_null | `reward` and `currency` are NULL for GitHub issues |
| test_state_mapped | `state` mapped to `"open"` or `"closed"` |
| test_canonical_issue_key | `canonical_issue_key` = `owner/repo#number` |

### 14.2 Pull Request Tests

| Test | Description |
|------|-------------|
| test_pr_excluded_from_candidates | PR object (with `pull_request` field) excluded from candidates list |
| test_pr_raw_evidence_preserved_or_not | Document behavior: Approach A (not fetched) or Approach B (preserved) |
| test_issues_only_filter | API call uses `filter=issues` parameter |

### 14.3 Pagination Tests

| Test | Description |
|------|-------------|
| test_single_page | One page of results → correct candidates |
| test_multiple_pages | Multiple pages → all candidates collected |
| test_end_of_pagination | Empty page → stops fetching |
| test_max_pages_bound | `max_pages=3` → stops after 3 pages even if more exist |
| test_max_candidates_bound | `max_candidates=10` → stops after 10 candidates |
| test_per_page_parameter | `per_page` passed to API |

### 14.4 Authentication Tests

| Test | Description |
|------|-------------|
| test_token_present | `GITHUB_TOKEN` set → Authorization header included |
| test_token_absent | `GITHUB_TOKEN` unset → no Authorization header, anonymous mode |
| test_invalid_token | 401 response → FAILED or PARTIAL |
| test_token_not_in_logs | Verify log output contains no token value |
| test_token_not_in_error | `AdapterResult.error` contains no token value |
| test_token_not_in_evidence | Raw evidence file contains no token |

### 14.5 HTTP Failure Tests

| Test | Description |
|------|-------------|
| test_401_unauthorized | 401 response → appropriate failure behavior |
| test_403_forbidden | 403 response → appropriate failure behavior |
| test_404_not_found | 404 for repository → that repository fails, others continue |
| test_429_rate_limited | 429 response → rate_limit_hit=True, PARTIAL/FAILED |
| test_5xx_server_error | 5xx response → PARTIAL/FAILED |
| test_timeout | Connection timeout → PARTIAL/FAILED |
| test_malformed_json | Non-JSON response → FAILED |
| test_missing_fields | Issue missing required fields → FAILED for that issue |

### 14.6 Empty Result Tests

| Test | Description |
|------|-------------|
| test_success_with_zero_candidates | Empty repository → SUCCESS + 0 candidates (not FAILED) |
| test_all_repos_empty | All configured repos empty → SUCCESS + 0 candidates |

### 14.7 Raw Evidence Tests

| Test | Description |
|------|-------------|
| test_raw_payload_is_full_issue | `raw_payload` contains complete GitHub issue object |
| test_raw_payload_extra_fields | Extra GitHub fields (comments, user, milestone, etc.) preserved |
| test_raw_payload_not_reconstructed | Raw payload is the API response, not built from BountyCandidate fields |
| test_sha256_verified | Stored file SHA-256 matches `raw_payload_hash` |
| test_no_credential_in_evidence | Raw evidence file contains no token/credential |

### 14.8 Deduplication Tests

| Test | Description |
|------|-------------|
| test_repeated_issue_deduplicated | Same `source_id` fetched twice → engine deduplicates, one candidate persisted |
| test_source_id_stable | Same issue produces same `source_id` across runs |

### 14.9 Integration Tests

| Test | Description |
|------|-------------|
| test_github_adapter_through_runtime | GitHub Adapter → Discovery Runtime → Discovery Engine → Raw Storage → SQLite end-to-end |
| test_multiple_repositories | Two configured repositories → candidates from both |
| test_failure_isolation | Repository A fails, Repository B succeeds → PARTIAL with B's candidates |
| test_engine_limits_respected | 201+ candidates → engine caps at 200, adapter respects lower limit |

### 14.10 Security Tests

| Test | Description |
|------|-------------|
| test_issue_body_treated_as_data | Issue body with prompt-like content (e.g., "Ignore previous instructions and...") → stored as string, not executed |
| test_no_hermesc_invocation | Verify no Hermes/LLM component is called during adapter fetch |
| test_no_instruction_interpretation | Issue body content never passed to any instruction-processing component |

### 14.11 Deterministic Fixtures

All tests use **deterministic mocked API responses**, not live GitHub API calls. Mock HTTP responses are provided via:
- A test HTTP client that returns pre-constructed JSON responses
- Or pre-serialized JSON fixture files

No live GitHub API access is required for the normal test suite.

---

## 15. ARCHITECTURE VALIDATION

### 15.1 Does GH-3B remain collector/normalizer only?

**YES.** GH-3B fetches GitHub issues, normalizes them to BountyCandidate, stores raw evidence. No policy, triage, profiling, selection, EV, acceptance prediction, implementation, or submission logic.

### 15.2 Does it reuse GH-2A?

**YES.** GH-3B produces BountyCandidate objects consumed by the existing DiscoveryEngine. Validation, deduplication, persistence, audit events all handled by GH-2A engine.

### 15.3 Does it reuse GH-2B?

**YES.** Raw evidence stored via existing RawStorage with SHA-256 integrity, content-addressed storage, path safety. Provenance fields (`raw_payload_reference`, `raw_payload_hash`) set by engine.

### 15.4 Does it reuse GH-2C?

**YES.** GitHub adapter is registered in AdapterRegistry as `source="github"`. DiscoveryRuntime loads config, resolves adapter, executes through DiscoveryEngine. Runtime remains source-agnostic.

### 15.5 Does generic runtime remain source-agnostic?

**YES.** Runtime has no GitHub-specific logic. It treats `"github"` as a source string. All GitHub behavior is in the adapter.

### 15.6 Are secrets isolated?

**YES.** `GITHUB_TOKEN` read from environment, used for HTTP Authorization header, discarded. Never stored in SQLite, raw evidence, logs, events, error messages, or candidates.

### 15.7 Is raw evidence the actual source payload?

**YES.** `raw_payload` is the complete GitHub API response object for each issue, stored as-is per GH-2B canonicalization rules. Not reconstructed from BountyCandidate.

### 15.8 Is pagination bounded?

**YES.** Adapter enforces `max_pages` and `max_candidates` from config. Stops on empty page, max pages, max candidates, or unrecoverable error. No unbounded fetching.

### 15.9 Are PRs handled deterministically?

**YES.** PRs detected via `pull_request` field. Excluded from candidates by default (using `filter=issues` API parameter). Behavior is deterministic and documented.

### 15.10 Is external content treated as untrusted data?

**YES.** GitHub issue content is data, never instructions. Security invariant documented in Section 11. GH-3B must not send issue content to Hermes/LLM and must not interpret it as instructions.

### 15.11 Contract Compatibility Summary

| Contract | Compatibility |
|----------|---------------|
| BountyCandidate | FULL — all fields mappable from GitHub issue |
| AdapterResult | FULL — status, candidates, pages, candidates_fetched, error, rate_limit_hit, elapsed_seconds |
| RunContext | FULL — source_config carries per-repository config |
| DiscoveryAdapter protocol | FULL — source="github", adapter_version, fetch(run_context) |
| RawStorage | FULL — stores complete issue payload as JSON |
| DiscoveryEngine | FULL — delegates validation, dedup, persistence, limits |
| DiscoveryRuntime | FULL — registered adapter, config mapping, deterministic execution |
| Database schema | FULL — bounties table has all needed columns |

---

## 16. SCOPE AUDIT

| Area | Status |
|------|--------|
| Production GitHub adapter implemented | **NO** — GH-3A is specification only |
| Network calls executed | **NO** — no real API requests |
| Scheduler | **NO** |
| CLI expansion | **NO** |
| Policy Engine | **NO** |
| Triage Engine | **NO** |
| Repository Profiler | **NO** |
| Context Engine | **NO** |
| Benchmark Engine | **NO** |
| LLM integration | **NO** |
| Hermes integration | **NO** |
| Git automation | **NO** |
| Repository cloning | **NO** |
| PR automation | **NO** |
| Autonomous submission | **NO** |
| EV scoring | **NO** |
| Acceptance prediction | **NO** |
| Acceptance probability | **NO** |
| Task selection | **NO** |

---

## 17. CHANGED FILES

This phase produces exactly one new file:

| File | Purpose |
|------|---------|
| `docs/discovery/phase-3a-github-adapter-spec.md` | Frozen GH-3B specification and contract review |

No production code is created. No existing files are modified. No tests are added (test plan is in the spec; implementation tests come in GH-3B).

---

## 18. UNRESOLVED QUESTIONS / RISKS

### 18.1 source_id Format

- **Question:** Should `source_id` be `"owner/repo#123"` or `"123"`?
- **Recommendation:** `"owner/repo#123"` to avoid cross-repository collision
- **Human decision required**

### 18.2 Rate Limit Behavior on 429

- **Question:** On 429, should adapter sleep until reset (reading `X-RateLimit-Reset`), or immediately return PARTIAL/FAILED?
- **Recommendation:** GH-3B does NOT implement sleep/retry (deferred). Immediately stop and return PARTIAL if some candidates fetched, FAILED if none.
- **Human decision required**

### 18.3 Anonymous Mode Viability

- **Question:** Is anonymous mode (no token, 60 req/hour) sufficient for GH-3B, or must a token be required?
- **Risk:** Without token, large repositories with many pages cannot be fully fetched
- **Human decision required**

### 18.4 PR Raw Evidence

- **Question:** Should raw evidence be preserved for PRs even though they are excluded from candidates?
- **Recommendation:** Approach A — use `filter=issues` to not fetch PRs at all. Simpler and cleaner.
- **Human decision required**

### 18.5 `since` Parameter

- **Question:** Should `since` be supported as a configuration parameter for incremental discovery?
- **Status:** Specified as optional in Section 3.3 and 10.1, but not required for initial implementation
- **Human decision required**

### 18.6 Label Filtering

- **Question:** Should `labels` parameter filter to only issues with specific labels (e.g., `"bug"`)?
- **Status:** Specified as optional in Section 3.3 and 10.1
- **Human decision required**

### 18.7 Private Repositories

- **Question:** Should GH-3B support private repositories when authenticated?
- **Status:** Technically possible with valid token scope, but not required for initial implementation
- **Human decision required**

### 18.8 Token Scope Verification

- **Question:** Should the adapter verify that the token has appropriate scope before fetching?
- **Status:** Not required — 403 response will indicate insufficient scope
- **Human decision required**

---

## 19. RECOMMENDATION

### 19.1 STATUS

**READY FOR GH-3B IMPLEMENTATION**

The specification is complete, internally consistent, and compatible with all existing GH-1/GH-2A/GH-2B/GH-2C contracts.

### 19.2 CONDITIONS FOR GH-3B

Before GH-3B implementation begins, human review must resolve:

1. **source_id format** — `"owner/repo#123"` vs `"123"`
2. **Rate limit behavior on 429** — immediate stop vs sleep
3. **Anonymous mode requirement** — optional or required
4. **PR raw evidence** — Approach A (not fetched) confirmed
5. **Optional parameters** — which of `since`, `labels`, `sort`, `direction` are enabled for initial implementation

### 19.3 BLOCKED ITEMS

None blocking. All unresolved questions are configuration/decision items, not architectural blockers.

### 19.4 RECOMMENDATION

**PROCEED TO GH-3B** after human resolution of the five decision items above.

---

## 20. STOP CONDITION

This is GH-3A — specification and contract review only.

**After producing this report:**

- STOP
- Do NOT implement GH-3B
- Do NOT make real GitHub API requests
- Do NOT add network dependencies
- Do NOT add scheduler
- Do NOT modify Policy/Triage/Profiler/Context engines
- Do NOT integrate LLM or Hermes
- Do NOT clone repositories
- Do NOT create branches, commits, or PRs
- Do NOT submit anything
- Do NOT implement acceptance prediction or EV scoring
- Do NOT modify GH-2A/B/C behavior
- Do NOT modify Phase 0 state machine

Wait for human architectural review of this specification before proceeding to GH-3B.

---

## 21. GITHUB / AUTHORSHIP RULE

I am the executor only.

I have NOT:
- Committed as Hermes
- Configured GitHub identity as Hermes/bot/agent
- Added myself as contributor
- Added agent attribution
- Pushed to any remote

I will NOT do any of these unless explicitly instructed by the human.

---

*End of GH-3A Specification.*
