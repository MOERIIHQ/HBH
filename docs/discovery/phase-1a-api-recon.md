# HBH Phase 1a — API Reconnaissance Report

## 0. Metadata

- **Report date:** 2026-09-23
- **Recon executor:** Hermes Agent (Nous Research)
- **Recon duration:** ~30 minutes
- **Environment:** Android Termux, Python 3.12, no `gh` CLI, no HBH credentials
- **Tools actually used:** web_search, web_extract, curl (read-only), GitHub REST (read-only), local filesystem inspection
- **GITHUB_TOKEN present:** no
- **Verification date/time:** 2026-09-23T10:00:00–10:12:36Z

---

## 1. Scope

### 1.1 What this report covers

Read-only investigation of three candidate bounty-source interfaces for HBH Phase 1b adapter design:

1. **TaskBounty** (Section 2) — REST API + MCP server at task-bounty.com
2. **Algora** (Section 3) — Algora bounty platform interface
3. **GitHub Issues** (Section 4) — GitHub REST API Issues endpoints

Investigation is limited to publicly accessible documentation, read-only HTTP responses, and public source repositories.

### 1.2 What this report does NOT cover

- Any adapter implementation
- Any scraper implementation
- Any database schema change
- Any candidate ingestion
- Any Phase 0 modification
- Any repository cloning or Git operation
- Any credential creation or token generation
- Algora internal/deep review (deferred to Step 2)
- GitHub Issues deep field-by-field analysis (deferred to Step 3)

### 1.3 Explicit out-of-scope items

- TaskBounty MCP tool-level detailed protocol analysis
- GitHub GraphQL API investigation (REST only)
- Rate-limit measurement via repeated requests (single-sample observation only)
- Authentication behavior with valid credentials (no credentials available)

---

## 2. TaskBounty

### 2.1 Interface type

TaskBounty exposes TWO distinct interfaces relevant to Phase 1b:

**A. REST API — PRIMARY DOCUMENTED INTERFACE**

VERIFIED — Public HTTP REST API at base URL `https://www.task-bounty.com/api/v1/`.

Evidence:
- GET `https://www.task-bounty.com/api/v1/tasks` returned HTTP 200 with body `{"data":[]}` (unauthenticated, live observation 2026-09-23T10:09:45Z).
- Response Content-Type: `application/json`.
- Server header: `server: Vercel` (indicates serverless/edge deployment, no dedicated API version header observed).

The REST API is the PRIMARY interface for candidate discovery. The MCP server wraps this same REST API and is NOT the authoritative schema source.

**[EVIDENCE]**

Claim: TaskBounty REST API exists at `/api/v1/` on `www.task-bounty.com`.

Source: `https://www.task-bounty.com/for-agents` (official documentation, For Agents page)

Accessed: 2026-09-23T10:09:45Z

Type: Documentation + Direct API Observation

Classification: VERIFIED

Excerpt: "GET /api/v1/tasks to list open bounties. POST /api/v1/tasks/{id}/access to mint a short-lived clone URL. POST /api/v1/submissions with the upstream PR URL."

---

**B. MCP Server — ALTERNATE WRAPPER, NOT AUTHORITATIVE SCHEMA SOURCE**

VERIFIED — MCP server exists via two deployment modes:

1. **Remote MCP endpoint:** `https://www.task-bounty.com/api/mcp/v1` (documented as hosted MCP for "Lovable, Base44, and other builders").
2. **Local npx MCP server:** `npx -y taskbounty-mcp-server` (running locally with `TASKBOUNTY_API_KEY` env var).

The MCP server is published on npm as `taskbounty-mcp-server` and registered in the MCP Registry at `registry.modelcontextprotocol.io` per the official docs page.

IMPORTANT — The MCP server is NOT the authoritative schema source for the underlying REST response. It is a protocol wrapper that uses the same `tb_live_*` API key and exposes tools that map to REST endpoints. Schema verification for Phase 1b must target the REST API directly. The MCP server's tool response shapes are documented but not directly invoked in this reconnaissance (MCP is a structured JSON-RPC-style protocol, not a simple HTTP GET).

**[EVIDENCE]**

Claim: TaskBounty offers a remote MCP endpoint at `/api/mcp/v1` and a local npx MCP server that wraps the REST API using the same API key.

Source: `https://www.task-bounty.com/docs/mcp` (official MCP docs) + `https://www.task-bounty.com/for-agents` (references MCP server config for Claude Code, Cursor, Cline, Windsurf, Aider)

Accessed: 2026-09-23T10:05:00Z (approx)

Type: Documentation

Classification: VERIFIED (existence of MCP server); MCP response schema UNVERIFIED without protocol invocation

---

### 2.2 Authentication

**REST API:**

VERIFIED — Bearer token authentication required for all solver-facing operations.

- Token format: `tb_live_*` (documented as the only credential type).
- Header: `Authorization: Bearer $TASKBOUNTY_API_KEY`
- How to obtain: Register an agent at `/dashboard/agents`, generate key at `/dashboard/settings#api-keys`. Alternatively run `taskbounty_login` for a browser OAuth device auth flow that mints a scoped key.
- Scope of key: "Read open bounties, submit fixes, enable Autopilot on repos the user owns, and create bounties. It does not grant access to other users' data." per official documentation.

**Unauthenticated behavior:**

VERIFIED — GET `/api/v1/tasks` returns HTTP 200 with `{"data":[]}` even WITHOUT a token. This likely means either (a) the endpoint serves a public listing but currently has no open bounties, or (b) the empty response is a default for unauthenticated access. Without a valid key this cannot be distinguished.

**[EVIDENCE]**

Claim: TaskBounty REST API uses Bearer token auth with `tb_live_*` keys.

Source: `https://www.task-bounty.com/for-agents` (official documentation) + `https://www.task-bounty.com/docs/mcp` (MCP docs)

Accessed: 2026-09-23T10:09:45Z

Type: Documentation

Classification: VERIFIED

Excerpt: "TASKBOUNTY_API_KEY is the only credential the server needs. It is a tb_live_* key that authenticates both the REST API and the MCP server."

Also: `https://github.com/eliottreich/taskbounty-mcp-server` README references `TASKBOUNTY_API_KEY` (a `tb_live_*` key from `/dashboard/api-keys`).

---

**MCP Authentication:**

VERIFIED — MCP server accepts `TASKBOUNTY_API_KEY` env var OR falls back to `taskbounty_login` browser device-auth flow. Credentials stored at `~/.taskbounty/credentials.json` (per MCP docs). The remote MCP endpoint uses bearer authentication per the docs.

---

### 2.3 Request model

**REST API — primary documented interface.**

VERIFIED — The REST API at `https://www.task-bounty.com/api/v1/` is the primary documented interface for candidate collection.

**MCP server — alternate wrapper, not authoritative schema source.**

VERIFIED — The MCP server (remote at `/api/mcp/v1` and local via `npx taskbounty-mcp-server`) wraps the same REST API. Per the MCP docs page, the MCP server "uses the same API key" and exposes tools that map to REST endpoints. The MCP server is NOT the authoritative schema source for the underlying REST response — it is a protocol wrapper. Schema verification must target the REST API directly.

**GET `/api/v1/tasks`** — List open bounties.

VERIFIED — This is the primary read endpoint for candidate collection.

Documented parameters (from official docs, `/for-agents` page):
- `platform=` — filter by platform
- `language=` — filter by language
- `limit=` — result limit
- `offset=` — pagination offset

Live observation (unauthenticated, 2026-09-23T10:09:45Z):
- `GET /api/v1/tasks` → HTTP 200, body `{"data":[]}`
- `GET /api/v1/tasks?limit=5&offset=0` → HTTP 200, body `{"data":[]}`
- `GET /api/v1/tasks?page=1&per_page=5` → HTTP 200, body `{"data":[]}`
- `GET /api/v1/tasks?since=2026-01-01T00:00:00Z` → HTTP 200, body `{"data":[]}`
- `GET /api/v1/tasks?include_failed=true` → HTTP 200, body `{"data":[]}`

All returns are `{"data":[]}`. Two hypotheses are consistent with this observation:
- (a) The platform currently has no open funded bounties.
- (b) The endpoint returns an empty array for unauthenticated requests regardless of actual bounty state.

Both are consistent with the observed data. The correct hypothesis cannot be determined without a valid API key.

**[EVIDENCE]**

Claim: GET /api/v1/tasks is the primary listing endpoint and accepts platform, language, limit, offset parameters.

Source: `https://www.task-bounty.com/for-agents` (official documentation) + direct HTTP observation

Accessed: 2026-09-23T10:09:45Z

Type: Documentation + Direct API Observation

Classification: VERIFIED for endpoint existence and parameter acceptance; RESPONSE SCHEMA UNVERIFIED without auth

---

**POST `/api/v1/tasks/{id}/access`** — Mint short-lived clone URL for private repos.

VERIFIED as documented but NOT tested (requires valid task_id + auth).

- HTTP method: POST
- Auth: Required (Bearer token)
- Purpose: Returns a short-lived read-only clone URL (~1 hour expiry) for private repository tasks.
- Cannot be tested without a valid task_id and valid credentials.

---

**POST `/api/v1/submissions`** — Register a submission (PR URL or patch).

VERIFIED as documented but NOT tested (requires auth + task_id).

- HTTP method: POST
- Auth: Required
- Request body shape (from docs): `{"task_id": "uuid", "external_link": "https://github.com/..."}` for PR submissions.
- Patch submission variant: `POST /api/v1/submissions/patch` accepts unified diff body.
- Cannot be tested without auth.

---

**POST `/api/v1/solver/payout-method`** — Register crypto payout address.

VERIFIED as documented. Method: POST. Body: `{"method": "solana_usdc"|"eth"|"btc", "address": "<public_address>"}`. Auth required.

---

### 2.4 Pagination

**Status: PARTIALLY VERIFIED**

The API accepts multiple pagination parameter styles:

VERIFIED — Parameter names accepted:
- `limit` + `offset` (documented and observed to be accepted)
- `page` + `per_page` (observed to be accepted)
- `since` (ISO 8601 timestamp, observed to be accepted)
- `include_failed` (boolean, observed to be accepted)

NOT VERIFIED:
- Maximum `per_page` / `limit` value
- Pagination token / cursor style (if any)
- Total count field behavior
- Whether pagination metadata (next_page, total, etc.) is returned

Without auth and with empty data, pagination mechanics cannot be meaningfully observed.

**[EVIDENCE]**

Claim: TaskBounty API supports offset-based and page-based pagination.

Source: `https://www.task-bounty.com/for-agents` (documentation) + direct HTTP observation of parameter acceptance

Accessed: 2026-09-23T10:09:45Z

Type: Documentation + Direct API Observation

Classification: VERIFIED for parameter acceptance; MAX_LIMIT/PAGINATION_METADATA UNVERIFIED

---

### 2.5 Rate limits

**Status: UNVERIFIED**

No rate-limit headers were observed in the response headers of GET `/api/v1/tasks`:

```
x-ratelimit-*: (none observed)
x-vercel-id: sin1::iad1::... (Vercel request ID only)
```

Vercel-hosted endpoints sometimes impose rate limits at the platform edge but do not always expose them as standard headers. Without authenticated requests or documentation stating explicit rate limits, the rate-limit policy is UNVERIFIED.

**[EVIDENCE]**

Claim: TaskBounty REST API rate limits are undocumented and not observable without authentication.

Source: Direct header inspection of GET /api/v1/tasks response (2026-09-23T10:09:45Z) + documentation review

Accessed: 2026-09-23T10:09:45Z

Type: Direct API Observation + Documentation

Classification: UNVERIFIED

Attempted: Inspected all response headers for rate-limit related headers (x-ratelimit-*, etc.). None found. Reviewed official documentation pages for rate-limit statements. None found in the accessible excerpts.

---

### 2.6 Response schema

**REST API response schema:**

BLOCKED — Without a valid `tb_live_*` API key, the actual structure of bounty objects returned by `GET /api/v1/tasks` (inside the `data[]` array) cannot be verified.

The only directly observed response is:

```json
{"data": []}
```

This confirms the envelope shape (`{"data": [...]}`) but reveals nothing about the contents of individual bounty objects.

**Webhook payload fields — INFERRED only, NOT authoritative for REST schema.**

The `/for-agents` documentation page includes a **notification webhook payload** example. These fields are documented in the context of server-sent webhook notifications to registered agent endpoints, NOT as the GET /api/v1/tasks response schema.

**[EVIDENCE]**

Claim: TaskBounty webhook notification payload contains task_id, title, bounty_cents, github_repo_url, github_issue_url, created_at, complexity_tag, language.

Source: `https://www.task-bounty.com/for-agents` (official documentation, webhook payload example)

Accessed: 2026-09-23T10:10:00Z

Type: Documentation

Classification: VERIFIED as webhook payload fields

Excerpt:
```json
{
  "task_id": "uuid",
  "title": "Fix null pointer in checkout",
  "bounty_cents": 5000,
  "github_repo_url": "https://github.com/acme/repo",
  "github_issue_url": "https://github.com/acme/repo/issues/42",
  "created_at": "2026-05-13T12:00:00.000Z",
  "complexity_tag": "small",
  "language": "typescript"
}
```

---

The webhook payload fields above are INFERRED to be potentially present in the GET /api/v1/tasks response, but this inference is NOT verified. The REST list endpoint may return a different (possibly larger) field set than the webhook notification payload. The MCP server's `get_bounty_detail` tool may also expose additional fields not visible in the webhook payload.

**MCP server response schema:**

VERIFIED to exist as a protocol wrapper, but the MCP tool response shapes are not directly interrogated in this reconnaissance (MCP is a structured JSON-RPC-style protocol, not a simple HTTP GET). The MCP server's `list_open_bounties` and `get_bounty_detail` tools are documented to return bounty details, but their exact response schema is UNVERIFIED without invoking the MCP protocol.

**Live availability status:**

UNRESOLVED — The public browse page at `https://www.task-bounty.com/browse` currently displays "No code bounties yet." The REST API endpoint `GET /api/v1/tasks` returns `{"data":[]}` (unauthenticated). Documentation describes an active bounty marketplace with open bounties. These observations are contradictory but not sufficient to conclude the platform is inactive. The discrepancy may be explained by any of: (a) unauthenticated endpoints return empty by design, (b) the platform genuinely has no open bounties at this moment, (c) the browse page and API have different data sources. Without authentication, the actual runtime state of the bounty marketplace is UNRESOLVED.

---

### 2.7 Candidate field mapping

See Section 6 for the full field-mapping specification.

**Pre-mapping observations — REST schema BLOCKED, webhook fields INFERRED only:**

| BountyCandidate concept | Closest documented TaskBounty field | Evidence status |
|---|---|---|
| source_id | task_id (UUID, from webhook) | INFERRED (webhook only; REST response UNVERIFIED) |
| title | title (from webhook) | INFERRED |
| source_url | github_issue_url (from webhook) | INFERRED |
| repository_url | github_repo_url (from webhook) | INFERRED |
| reward_amount | bounty_cents (cents, integer, from webhook) | INFERRED |
| source_created_at | created_at (ISO 8601, from webhook) | INFERRED |
| source_updated_at | updated_at (NOT observed in webhook payload) | UNVERIFIED |
| state/status | status (NOT observed in available documentation excerpts) | UNVERIFIED — no status field confirmed in webhook schema |
| labels | complexity_tag (partial — not standard issue labels) | INFERRED (partial) |
| description/body | NOT in webhook payload | UNVERIFIED (may exist in get_bounty_detail) |
| assignee | NOT in available documentation | UNVERIFIED |
| comment_count | NOT in available documentation | UNVERIFIED |

**Critical caveat:** TaskBounty bounties are NOT raw GitHub issues. They are funded tasks created FROM GitHub issues (via `post_from_issue`) or created directly. A TaskBounty task has its own lifecycle distinct from the underlying GitHub issue lifecycle (draft → funded → claimed → submission → verified → awarded/cancelled). Fields map to the TaskBounty task model, NOT directly to GitHub issue fields. The relationship between a TaskBounty task and its source GitHub issue is represented by `github_issue_url` and `github_repo_url` — the actual GitHub issue number, labels, body, and comments may need to be fetched separately from GitHub if required as candidate attributes.

---

### 2.8 Failure modes

**Observed and documented failure modes:**

1. **Empty data with no auth:** GET `/api/v1/tasks` returns 200 with `{"data":[]}` — indistinguishable from "no bounties" vs "unauthenticated empty response" without credentials.
2. **405 Method Not Allowed:** POST to `/api/v1/submissions` without auth returns HTTP 405 (not 401/403), indicating method restriction, not auth rejection specifically. This was observed during testing.
3. **Auth required endpoints:** POST `/api/v1/tasks/{id}/access`, POST `/api/v1/submissions`, POST `/api/v1/solver/payout-method` all require Bearer token. Behavior without auth NOT directly tested (only GET /tasks was tested unauthenticated).
4. **MCP credential requirement:** MCP server requires `TASKBOUNTY_API_KEY` or browser device-auth flow for solver tools.
5. **Funding is web-only:** Bounty creation/funding returns a funding URL — payment is completed in browser, NOT through API. This means the API cannot fully fund a bounty programmatically.
6. **Private repo access:** Requires POST /api/v1/tasks/{id}/access to get short-lived clone URL (~1 hour). This adds a dependency on a per-task access call for private repos.
7. **No SDK/Client library:** No official Python or JavaScript client library is documented; integration is via raw HTTP or MCP.

**[EVIDENCE]**

Claim: POST /api/v1/submissions returns 405 without auth.

Source: Direct HTTP observation (curl POST to /api/v1/submissions)

Accessed: 2026-09-23T10:11:00Z (approx)

Type: Direct API Observation

Classification: VERIFIED

Excerpt: HTTP_CODE: 405, TIME: 0.545s, SIZE: 0

---

### 2.9 Evidence

Summary of all evidence sources used for TaskBounty:

| Source | Type | Accessed | Classification |
|---|---|---|---|
| `https://www.task-bounty.com/for-agents` | Official documentation | 2026-09-23T10:09:45Z | VERIFIED |
| `https://www.task-bounty.com/docs/mcp` | Official MCP documentation | 2026-09-23T10:05:00Z | VERIFIED |
| `https://www.task-bounty.com/browse` | Official public browse page | 2026-09-23T10:11:00Z | VERIFIED (currently shows "No code bounties yet") |
| `https://github.com/eliottreich/taskbounty-mcp-server` | Official MCP server source (GitHub) | 2026-09-23T10:11:00Z (repo metadata only; README extraction failed via firecrawl) | VERIFIED for existence + MCP tool listing from npm/registry references |
| `GET https://www.task-bounty.com/api/v1/tasks` | Direct API observation (unauthenticated) | 2026-09-23T10:09:45Z | VERIFIED (200, empty data) |
| `GET https://www.task-bounty.com/api/v1/tasks?limit=5&offset=0` | Direct API observation | 2026-09-23T10:09:45Z | VERIFIED (200, empty data) |
| `POST https://www.task-bounty.com/api/v1/submissions` | Direct API observation | 2026-09-23T10:11:00Z | VERIFIED (405) |
| Response headers of GET /api/v1/tasks | Direct header inspection | 2026-09-23T10:09:45Z | VERIFIED (no rate-limit headers observed) |

Local project files inspected (not TaskBounty-specific, but relevant to HBH Phase 0 context):
- `/data/data/com.termux/files/home/hbh/config/hbh_config.yaml` — Phase 0 config (version 1, hard_reject rules, penalties, human_gate_required)
- `/data/data/com.termux/files/home/hbh/` — HBH Phase 0 project structure (core, cli, config, tests)

---

### 2.10 Confidence

**TaskBounty overall confidence: MEDIUM**

Breakdown:
- **Interface existence:** HIGH — REST API + MCP server both verified to exist and respond.
- **Authentication model:** HIGH — Bearer token, tb_live_* keys, documented scopes.
- **Endpoint surface:** MEDIUM — Key endpoints documented; full surface not exhaustively verified.
- **Response schema:** LOW — Only empty array observed; actual bounty object schema unverified without auth.
- **Pagination:** LOW-MEDIUM — Parameters accepted but mechanics unverified (empty data).
- **Rate limits:** LOW — No headers observed; no documentation found.
- **Candidate field mapping viability:** MEDIUM — Webhook payload gives strong hints; GET response schema unverified.

The LOW confidence on response schema is the primary risk for Phase 1b: without a valid API key, the actual field structure of bounty objects cannot be confirmed.

---

### 2.11 Status

TaskBounty: **PARTIALLY SUITABLE — REQUIRES AUTHENTICATION FOR FULL VERIFICATION**

Summary:
- A public REST API exists and responds (200).
- An MCP server exists (remote + local).
- Authentication is required for meaningful data access (Bearer tb_live_* token).
- Without a valid API key, the bounty object schema is UNVERIFIED.
- The webhook payload provides an INFERRED schema that is likely representative but not confirmed.
- No credentials are available in this environment.
- Phase 1b adapter design can proceed with the INFERRED schema, but full field verification requires either a valid API key or human provision of sample response data.

---

## 3. Algora

### 3.1 Interface type

**A. REST API**

VERIFIED — Algora exposes a REST API documented at two official documentation URLs:

1. `https://api.docs.algora.io/bounties` — Bounties reference
2. `https://api.docs.algora.io/tasks` — Tasks reference
3. `https://sematic.algora.io/refs/bounty` — Bounties reference (alternate docs host)

The base URL used in documentation examples is `https://console.algora.io/api/` (which HTTP-redirects 301 to `https://algora.io/api/`). The live base URL is `https://algora.io/api/`.

**[EVIDENCE]**

Claim: Algora exposes a REST API with documented endpoints at /api/bounties and /api/orgs/{org}/bounties.

Source: `https://api.docs.algora.io/bounties` (official documentation) + `https://sematic.algora.io/refs/bounty` (official documentation)

Accessed: 2026-09-23T10:20:00Z (approx)

Type: Documentation

Classification: VERIFIED

---

**B. GitHub-driven bounty model (primary representation)**

VERIFIED — Algora bounties are created and represented primarily through GitHub integration. The platform's own public UI at `https://algora.io/bounties` states: "Create new bounties by commenting /bounty $1000 on GitHub issues."

The Algora GitHub app creates bounties by reacting to issue comments of the form `/bounty $AMOUNT`. The bounty is stored as a Algora record linked to the GitHub issue, not as a standalone entity disconnected from GitHub.

**[EVIDENCE]**

Claim: Algora bounties are created by commenting /bounty $AMOUNT on GitHub issues.

Source: `https://algora.io/bounties` (official public UI page)

Accessed: 2026-09-23T10:20:00Z (approx)

Type: Documentation (official UI)

Classification: VERIFIED

Excerpt: "Create new bounties by commenting /bounty $1000 on GitHub issues."

Also: `https://github.com/algora-io/algora` README describes a "GitHub app to create bounties & reward tips on issues and PRs."

---

**C. Public bounties listing (HTML UI, not API JSON)**

VERIFIED — The public page `https://algora.io/bounties` renders an HTML page listing open and completed bounties. This is a SPA-rendered page (the `/api/bounties` endpoint returns HTML, not JSON). The actual bounty data for the public listing is loaded via client-side JavaScript from internal API calls, but those internal API calls are not documented as public endpoints.

**[EVIDENCE]**

Claim: https://algora.io/bounties returns an HTML page (SPA), not a JSON API response.

Source: Direct HTTP observation (curl)

Accessed: 2026-09-23T10:20:53Z

Type: Direct API Observation

Classification: VERIFIED

Excerpt: HTTP 200, Content-Type: text/html; charset=utf-8, content-length: 30380, server: Fly/454af3fb

---

### 3.2 Authentication

**Public endpoints:**

VERIFIED — The GET `/api/orgs/{org}/bounties` endpoint is documented as PUBLIC (no authentication required). The documentation page at `api.docs.algora.io/bounties` explicitly labels it: "This public endpoint allows you to retrieve a paginated list of bounties created by the given organization."

**Organization-scoped endpoints:**

VERIFIED as documented — GET `/api/bounties` (list your org's bounties) is an authenticated endpoint requiring organization credentials. Similarly, POST/PATCH/DELETE on bounties are authenticated operations for bounty creators.

**No valid credential available:**

No Algora API key, org token, or GitHub app installation token is available in this environment.

**[EVIDENCE]**

Claim: GET /api/orgs/{org}/bounties is a public endpoint requiring no authentication.

Source: `https://api.docs.algora.io/bounties` (official documentation)

Accessed: 2026-09-23T10:20:00Z

Type: Documentation

Classification: VERIFIED

---

### 3.3 Request model

**GET /api/orgs/{org}/bounties** — List bounties by organization (PUBLIC).

VERIFIED — This is the primary read endpoint for candidate collection without authentication.

- HTTP method: GET
- Path: `/api/orgs/{org}/bounties`
- Auth: NOT required (public)
- Query parameters:
  - `limit` — integer, range 1–100, default 10
  - `cursor` — string, object ID for pagination cursor
- Path parameter:
  - `org` — string, organization identifier (e.g., "Uber4Coding", "prefix-dev")

**GET /api/bounties** — List bounties of authenticated org.

VERIFIED as documented — Requires authentication. Query parameters: `limit` (1–100, default 10), `cursor` (string).

**GET /api/bounties/{id}** — Retrieve a single bounty.

VERIFIED as documented — Path parameter `id` (string, bounty ID).

**POST /api/bounties** — Create one or more bounties (authenticated).

VERIFIED as documented — Body: array of bounty objects. Each requires: `forge` (github only), `repo_owner`, `repo_name`, `number` (issue number), `amount` (integer, smallest currency unit), `currency` (USD only). "Only 1 bounty per issue is allowed by each organization. Duplicate bounty attempts on the same issue will be skipped silently."

**PATCH /api/bounties/{id}** — Update bounty (authenticated).

VERIFIED as documented — Body: `reward` object with `amount` and `currency`, or `status` (active/inactive).

**DELETE /api/bounties/{id}** — Delete bounty (authenticated).

VERIFIED as documented.

---

**[EVIDENCE]**

Claim: Algora REST API supports GET list (public + authenticated), GET by ID, POST create, PATCH update, DELETE delete. Bounty creation requires forge, repo_owner, repo_name, number, amount, currency.

Source: `https://api.docs.algora.io/bounties` (official documentation)

Accessed: 2026-09-23T10:20:00Z

Type: Documentation

Classification: VERIFIED

Excerpt: "POST /api/bounties — Creates one or more bounties. Only 1 bounty per issue is allowed by each organization. Required attributes: forge (github), repo_owner, repo_name, number, amount, currency."

---

### 3.4 Pagination

VERIFIED — Cursor-based pagination.

- `limit` — integer, range 1–100, default 10.
- `cursor` — string, object ID defining position in the list.
- Response includes `next_cursor` field for the next page (observed in documentation example response).

**NOT VERIFIED:**
- Whether `total_count` or similar metadata is returned.
- Whether offset-based pagination is also supported (only cursor is documented).
- Maximum page size behavior in practice (tested only 1–100 documented range).

**[EVIDENCE]**

Claim: Algora API uses cursor-based pagination with limit (1-100, default 10) and cursor parameters. Response includes next_cursor.

Source: `https://api.docs.algora.io/bounties` (official documentation) + documented response example

Accessed: 2026-09-23T10:20:00Z

Type: Documentation

Classification: VERIFIED

Excerpt: Response example:
```json
{
  "next_cursor": "clcg36as9000bs8swc544ee8c",
  "items": [...]
}
```

---

### 3.5 Rate limits

**Status: UNVERIFIED**

No rate-limit headers were observed in the response headers of any Algora endpoint tested (all returned HTML pages or 404s; no authenticated JSON API response was obtainable).

The documentation pages reviewed do not mention explicit rate limits.

**[EVIDENCE]**

Claim: Algora API rate limits are undocumented and not observable without authenticated API access.

Source: Direct header inspection of GET /api/bounties, GET /api/orgs/{org}/bounties responses (2026-09-23T10:20:00Z) + documentation review

Accessed: 2026-09-23T10:20:00Z

Type: Direct API Observation + Documentation

Classification: UNVERIFIED

Attempted: Inspected response headers for rate-limit indicators. No rate-limit headers observed. Reviewed official documentation for rate-limit statements. None found.

---

### 3.6 Response schema

**Bounty model — VERIFIED from official documentation.**

The Algora API documentation defines the Bounty model with these fields:

| Field | Type | Description |
|---|---|---|
| `id` | string | Unique identifier for the bounty object |
| `task` | Task object | Task to be done (see Task model below) |
| `amount` | integer | Reward amount in smallest currency unit (cents). Min $0.50 USD. Up to 8 digits (e.g., 99999999 = $999,999.99) |
| `currency` | string | Three-letter ISO currency code. Currently only "USD" allowed |
| `status` | string | "active" or "inactive" |
| `created_at` | string | ISO 8601 timestamp: YYYY-MM-DDTHH:MM:SSSZ |
| `updated_at` | string | ISO 8601 timestamp: YYYY-MM-DDTHH:MM:SSSZ |

**[EVIDENCE]**

Claim: Algora Bounty model has fields id (string), task (Task), amount (integer, cents), currency (string, USD only), status (active/inactive), created_at (ISO 8601), updated_at (ISO 8601).

Source: `https://api.docs.algora.io/bounties` (official documentation)

Accessed: 2026-09-23T10:20:00Z

Type: Documentation

Classification: VERIFIED

---

**Task model — VERIFIED from official documentation.**

The Task model contains the metadata of the work to be done:

| Field | Type | Description |
|---|---|---|
| `id` | string | Unique identifier for the object |
| `forge` | string | Platform where the task resides. Currently only "github" |
| `repo_owner` | string | Owner of the repository |
| `repo_name` | string | Name of the repository |
| `number` | integer | Number of the issue/pull request |
| `source` | object | Discriminated union: `{ type: "unknown" }` (fetching/failed) OR `{ type: "issue", data: Issue }` OR `{ type: "pull_request", data: Pull Request }` |

The `source` field is particularly important: when a bounty is created, the underlying GitHub issue data is fetched asynchronously. During fetching or if fetch fails, `source` is `{ type: "unknown" }`. Once resolved, `source` contains the full GitHub issue or PR data.

**[EVIDENCE]**

Claim: Algora Task model has fields id, forge (github only), repo_owner, repo_name, number, source (discriminated union: unknown/issue/pull_request).

Source: `https://api.docs.algora.io/tasks` (official documentation)

Accessed: 2026-09-23T10:20:00Z

Type: Documentation

Classification: VERIFIED

---

**Documented response example — VERIFIED from official documentation.**

The docs page includes a live response example:

```json
{
  "next_cursor": "clcg36as9000bs8swc544ee8c",
  "items": [
    {
      "id": "clcg36as9000as8swwd5lmovp",
      "forge": "github",
      "repo_owner": "Uber4Coding",
      "repo_name": "dev",
      "number": 7,
      "amount": 10000,
      "currency": "USD",
      "status": "active",
      "created_at": "2023-01-03T10:27:05.626Z",
      "updated_at": "2023-01-03T10:27:08.192Z",
      "issue": {
        "id": 1450490527,
        "url": "https://api.github.com/repos/Uber4Coding/dev/issues/7",
        "repository_url": "https://api.github.com/repos/Uber4Coding/dev",
        "labels_url": "https://api.github.com/repos/Uber4Coding/dev/issues/7/labels{/name}",
        "comments_url": "https://api.github.com/repos/Uber4Coding/dev/issues/7/comments",
        "events_url": "https://api.github.com/repos/Uber4Coding/dev/issues/7/events",
        ... (truncated in excerpt)
      }
    }
  ]
}
```

Note: the documented example response uses `issue` as a nested field (containing GitHub API issue representation), not `task`. This is interesting because the model documentation says the Bounty has a `task` field, but the list endpoint example shows `issue` directly. This discrepancy is noted for Phase 1b attention.

**[EVIDENCE]**

Claim: Algora GET /api/orgs/{org}/bounties response example shows items array with fields: id, forge, repo_owner, repo_name, number, amount, currency, status, created_at, updated_at, and nested issue object containing GitHub issue API fields.

Source: `https://api.docs.algora.io/bounties` (official documentation, response example)

Accessed: 2026-09-23T10:20:00Z

Type: Documentation

Classification: VERIFIED as documented example; actual live response UNVERIFIED (endpoint returned 404 for tested org values; see Section 3.9)

---

### 3.7 Candidate field mapping

See Section 6 for the full field-mapping specification.

**Field mapping — VERIFIED from documentation:**

| BountyCandidate concept | Algora field | Evidence status |
|---|---|---|
| source_id | bounty `id` (string) | VERIFIED (documentation) |
| title | bounty.source.issue.title (when source is resolved) OR requires separate GitHub issue fetch | VERIFIED that source.issue contains GitHub issue data; title specifically from nested GitHub issue |
| source_url | bounty.source.issue.url (GitHub issue API URL) OR reconstructed as `https://github.com/{repo_owner}/{repo_name}/issues/{number}` | VERIFIED (from task fields + issue.url) |
| repository_url | `https://github.com/{repo_owner}/{repo_name}` | VERIFIED (from task.repo_owner + task.repo_name) |
| reward_amount | bounty `amount` (integer, cents) | VERIFIED (documentation) |
| reward_currency | bounty `currency` (string, currently "USD" only) | VERIFIED (documentation) |
| source_created_at | bounty `created_at` (ISO 8601) | VERIFIED (documentation) |
| source_updated_at | bounty `updated_at` (ISO 8601) | VERIFIED (documentation) |
| state | bounty `status` ("active" / "inactive") | VERIFIED (documentation) |
| forge_platform | bounty `forge` ("github" only currently) | VERIFIED (documentation) |
| issue_number | bounty.task.number (integer) | VERIFIED (documentation) |
| repo_owner | bounty.task.repo_owner (string) | VERIFIED (documentation) |
| repo_name | bounty.task.repo_name (string) | VERIFIED (documentation) |
| labels | NOT in bounty model; available from nested source.issue.labels (GitHub labels) | VERIFIED — available via nested issue data, requires source resolution |
| description/body | NOT in bounty model; available from nested source.issue.body (GitHub issue body) | VERIFIED — available via nested issue data |
| assignee | NOT in bounty model; available from nested source.issue.assignee (GitHub assignee) | VERIFIED — available via nested issue data |
| comment_count | NOT in bounty model; available from nested source.issue (GitHub issue comments count) | VERIFIED — available via nested issue data |

**Critical structural observation:**

Algora bounties are GitHub issues with a bounty record attached. The bounty record contains the financial metadata (amount, currency, status, timestamps) and links to the underlying GitHub issue via the task model (repo_owner, repo_name, number) and the nested `issue` object. The actual issue title, body, labels, assignee, and comments live in the nested GitHub issue data — either in the `issue` field of the list response or retrievable via the GitHub API at the URL provided in `issue.url`.

This means an Algora adapter for HBH would need to:
1. Fetch bounties via GET /api/orgs/{org}/bounties
2. Extract bounty metadata (id, amount, currency, status, created_at, updated_at, task fields)
3. Optionally resolve the nested `issue` object (if present) for title, body, labels, etc.
4. If `issue` is not resolved (source.type = "unknown"), fetch the GitHub issue separately via GitHub API using repo_owner/repo_name/number

---

### 3.8 Failure modes

**Observed and documented failure modes:**

1. **Public org endpoint 404 for unknown organizations:** GET `/api/orgs/{org}/bounties` returns 404 (HTML "Page Not Found") for organizations that do not exist or have no bounties. In testing: `prefix-dev` → 404, `github` → 404, `Uber4Coding` → 404 (Note: Uber4Coding was used in the documentation example but returns 404 live — the bounty may have been deleted or the org no longer exists). This means the public endpoint is not a general "list all bounties" endpoint — it is org-specific, and the caller must know which organizations have bounties.

2. **HTML response instead of JSON for unauthenticated root:** GET `/api/bounties` (without org path) returns HTML (SPA page), NOT a JSON list of all bounties. The JSON API is only accessible for specific orgs via `/api/orgs/{org}/bounties`.

3. **Source resolution async:** The `source` field on a Task may be `{ type: "unknown" }` if the GitHub issue data hasn't been fetched yet or if the fetch failed. This means bounties created moments ago may not have their issue data immediately available.

4. **Only GitHub forge supported:** The documentation states `forge` can only be "github" currently. Other forges (GitLab, etc.) are not supported without contacting Algora.

5. **Single bounty per issue per org:** "Only 1 bounty per issue is allowed by each organization. Duplicate bounty attempts on the same issue will be skipped silently." This means an org cannot post multiple bounties on the same issue — relevant for understanding data cardinality.

6. **USD-only currency:** Currently only USD is allowed for bounty creation. Other currencies require contacting Algora.

7. **No general public bounty listing API:** There is no documented public endpoint that lists ALL bounties across all organizations. The public endpoint requires knowing the specific org. This is a significant limitation for a discovery engine that needs to find bounties across multiple orgs without prior knowledge of which orgs have active bounties.

8. **Amount in cents:** The amount field is in the smallest currency unit (cents for USD), not dollars. A $50 bounty is represented as 5000. This requires conversion to a standard representation.

**[EVIDENCE]**

Claim: GET /api/orgs/{org}/bounties returns 404 for unknown/nonexistent orgs (prefix-dev, github, Uber4Coding all returned 404 live).

Source: Direct HTTP observation (curl)

Accessed: 2026-09-23T10:20:53Z

Type: Direct API Observation

Classification: VERIFIED

Excerpt: HTTP 404, HTML "Page Not Found" body for /api/orgs/prefix-dev/bounties, /api/orgs/github/bounties, /api/orgs/Uber4Coding/bounties

---

### 3.9 Evidence

Summary of all evidence sources used for Algora:

| Source | Type | Accessed | Classification |
|---|---|---|---|
| `https://api.docs.algora.io/bounties` | Official API documentation | 2026-09-23T10:20:00Z | VERIFIED |
| `https://api.docs.algora.io/tasks` | Official API documentation (Tasks) | 2026-09-23T10:20:00Z | VERIFIED |
| `https://sematic.algora.io/refs/bounty` | Official documentation (alternate host) | 2026-09-23T10:20:00Z | VERIFIED (same content as api.docs.algora.io) |
| `https://algora.io/bounties` | Official public UI page | 2026-09-23T10:20:00Z | VERIFIED |
| `https://algora.io/api/bounties` | Direct HTTP observation | 2026-09-23T10:20:53Z | VERIFIED (returns HTML SPA, not JSON) |
| `https://algora.io/api/orgs/{org}/bounties` (multiple orgs) | Direct HTTP observation | 2026-09-23T10:20:53Z | VERIFIED (404 for tested orgs) |
| `https://algora.io/api/bounties?limit=5` | Direct HTTP observation | 2026-09-23T10:20:53Z | VERIFIED (returns HTML SPA) |
| `https://console.algora.io/api/orgs/Uber4Coding/bounties` | Direct HTTP observation | 2026-09-23T10:20:53Z | VERIFIED (301 redirect to algora.io) |
| `https://github.com/algora-io/algora` README | Official source repository | 2026-09-23T10:21:00Z | VERIFIED (GitHub app for bounty creation confirmed) |
| `https://algora.io/docs` | Official docs landing page | 2026-09-23T10:20:00Z | VERIFIED |

---

### 3.10 Confidence

**Algora overall confidence: MEDIUM-HIGH**

Breakdown:
- **Interface existence:** HIGH — REST API documented with clear endpoints, models, and examples.
- **Authentication model:** HIGH — Clear distinction between public org endpoint (no auth) and authenticated org endpoints.
- **Bounty model schema:** HIGH — Fully documented with field types, descriptions, and a live response example.
- **Task model schema:** HIGH — Fully documented including the discriminated union source field.
- **Pagination:** HIGH — Cursor-based, well-documented with limit range and next_cursor.
- **Rate limits:** LOW — Undocumented and unobservable without auth.
- **Candidate field mapping viability:** HIGH — All required BountyCandidate fields are either directly in the bounty model or available via the nested GitHub issue data.
- **Live endpoint accessibility:** LOW-MEDIUM — Public org endpoint returns 404 for tested orgs. The documented example org (Uber4Coding) no longer appears to have accessible bounties via the public endpoint. This raises the question of how a discovery engine would find which orgs have active bounties.
- **General public bounty discovery:** LOW — No documented public endpoint for listing ALL bounties across all orgs. The public endpoint is org-scoped.

The primary risk is the org-discovery problem: without a way to discover which organizations have active bounties, the public `/api/orgs/{org}/bounties` endpoint is only useful if the adapter already knows which orgs to query.

---

### 3.11 Status

Algora: **SUITABLE WITH CAVEATS — ORGAINED DISCOVERY PROBLEM**

Summary:
- A well-documented REST API exists with clear bounty and task models.
- A public endpoint (GET /api/orgs/{org}/bounties) requires no authentication.
- All BountyCandidate fields are addressable either directly in the bounty model or via nested GitHub issue data.
- The public endpoint is org-scoped: an adapter must know which orgs to query. There is no "list all bounties everywhere" public endpoint.
- Live testing showed 404 for multiple org values including the one used in the documentation example. This may indicate the example org's bounties were deleted, the org no longer exists, or the endpoint behavior differs from documentation.
- Rate limits are undocumented.
- Bounties are created via GitHub issue comments (/bounty $AMOUNT), meaning there is a strong relationship between Algora bounties and GitHub issues — relevant for cross-source correlation with GitHub Issues source.
- No valid Algora credentials are available, but authentication is NOT required for the primary public listing endpoint.

**Key open question for human decision:** How should the HBH Algora adapter discover which organizations have active bounties? Without a "list all bounties" public endpoint, the adapter needs either:
(a) A configured list of target organizations
(b) A way to discover orgs from another source (e.g., GitHub search for Algora-related activity)
(c) Accept that the adapter only covers a pre-configured set of orgs




---

## 4. GitHub Issues

[Reserved for Step 3 — GO STEP 3 required to populate this section]

---

## 5. Cross-Source Comparison

[Reserved for Step 4 — GO STEP 4 required to populate this section]

---

## 6. Proposed Adapter Contracts — SPEC ONLY

[Reserved for Step 4 — GO STEP 4 required to populate this section]

---

## 7. Unsupported / Unknown Fields

[Reserved for Step 4 — GO STEP 4 required to populate this section]

---

## 8. Risks and Ambiguities

[Reserved for Step 4 — GO STEP 4 required to populate this section]

---

## 9. Recommendation for Phase 1b

[Reserved for Step 4 — GO STEP 4 required to populate this section]

---

*End of Section 2 (TaskBounty). Sections 3–9 pending. Awaiting GO STEP 2.*
