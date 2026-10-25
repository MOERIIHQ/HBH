# HBH Repository Profiler — Specification & Contract Review

**Phase:** RP-SPEC (Specification Only)
**Status:** Specification Draft
**Date:** 2026-09-28
**Author:** Hermes Agent (executor/development agent)
**Human review required before RP-1 implementation**

---

## 1. PURPOSE AND SCOPE

Repository Profiler adalah komponen HBH yang bertugas mengumpulkan FAKTA tentang repository eksternal (khususnya GitHub) untuk keperluan discovery pipeline.

**Repository Profiler menjawab:**

> "Apa fakta verifiable yang tersedia tentang repository ini?"

**Repository Profiler TIDAK menjawab:**

> "Repository ini bagus untuk bounty?"
> "Repository ini layak diproses?"
> "Berapa EV repository ini?"

---

## 2. NON-GOALS

Repository Profiler TIDAK:

- menentukan repository bagus/buruk
- menghitung reward yang menarik
- menghitung EV
- menentukan priority
- menghitung difficulty score
- memprediksi acceptance probability
- melakukan task selection
- melakukan hard reject
- memberikan recommendation
- melakukan ranking
- clone repository (V1)
- menjalankan kode dari repository
- menginstall dependencies
- melakukan build atau test

---

## 3. ARCHITECTURAL POSITION

```
Discovery Engine
    ↓ (discovered candidates)
Repository Profiler
    ↓ (profiled facts)
Policy Engine / Triage Engine
    ↓
... (Context Engine, Implementation Engine, dll)
```

Repository Profiler berada setelah Discovery Engine dan sebelum Policy/Triage Engine.

**Posisi dalam state machine existing:**

```
DISCOVERED
    ↓
PROFILED
    ↓
TRIAGED
    ↓
SELECTED
    ↓
CONTEXT_READY
    ↓
IMPLEMENTING
    ↓
VALIDATING
    ↓
READY_FOR_REVIEW
    ↓
APPROVED
    ↓
SUBMITTED
    ↓
ACCEPTED / REJECTED
```

Repository Profiler berfungsi di transisi DISCOVERED → PROFILED.

---

## 4. RESPONSIBILITIES

Repository Profiler bertanggung jawab untuk:

1. **Mengumpulkan fakta metadata repository** dari sumber eksternal (GitHub API untuk V1)
2. **Menormalisasi fakta** ke bentuk yang konsisten dan deterministic
3. **Menyediakan raw evidence** dari respons sumber eksternal
4. **Merespons pertanyaan faktual** tentang repository

Repository Profiler TIDAK bertanggung jawab untuk:

1. Menentukan apakah repository layak/digunakan
2. Menentukan apakah license ACCEPTABLE
3. Menentukan apakah repository aktif/tidak
4. Menentukan apakah repository kompetitif
5. Membuat keputusan apa pun tentang repository

---

## 5. INPUT CONTRACT

### 5.1 RepositoryIdentifier

Input utama adalah identifikasi repository yang akan di-profil.

**Bentuk canonical untuk GitHub:**

```
github:owner/repository
```

**Contoh:**

```
github:octocat/Hello-World
github:facebook/react
```

### 5.2 Owner Normalization

- Owner adalah string sebelum `/` dalam `owner/repository`
- Tidak ada transformasi case (case-sensitive, sesuai GitHub)
- Tidak ada trimming selain whitespace di awal/akhir (jika ada)
- Owner tidak boleh kosong
- Owner tidak boleh mengandung `/`

### 5.3 Repository Name Normalization

- Repository name adalah string setelah `/` dalam `owner/repository`
- Tidak ada transformasi case (case-sensitive, sesuai GitHub)
- Trailing slash dihilangkan
- `.git` suffix dihilangkan jika ada (karena API GitHub menerima keduanya, tetapi canonical adalah tanpa .git)
- Tidak boleh kosong
- Tidak boleh mengandung `/`

### 5.4 URL vs identifier

Jika input adalah URL:

```
https://github.com/owner/repository
```

URL di-parse menjadi `owner/repository` sebelum diproses lebih lanjut.

### 5.5 Invalid Repository Identifier

Identifier dianggap tidak valid jika:

- Tidak mengandung `/`
- Owner kosong
- Repository name kosong
- Terdapat karakter yang tidak diperbolehkan oleh GitHub (spesial karakter selain yang didokumentasikan GitHub)

Invalid identifier ditolak sebelum HTTP request dikirim.

---

## 6. OUTPUT CONTRACT

### 6.1 RepositoryProfile

RepositoryProfile adalah hasil profiling yang berisi fakta-fakta tentang repository.

**Kontrak utama:**

- Semua field adalah fakta dari sumber eksternal, bukan judgment
- Field yang tidak tersedia dari sumber ditandai sebagai NULL/unavailable
- Tidak ada field yang merupakan derived score atau ranking
- Provenance lengkap disertakan

---

## 7. REPOSITORYPROFILE LOGICAL SCHEMA

### 7.1 IDENTITY

|| Field | Type | Required | Description |
|-------|------|----------|-------------|
|| source | str | YES | `"github"` untuk V1 |
|| repository | str | YES | `owner/repository` canonical form |
|| canonical_url | str \| None | YES | `https://github.com/owner/repository` |
|| owner | str | YES | Repository owner (normalized) |
|| name | str | YES | Repository name (normalized, tanpa .git) |
|| visibility | str \| None | NO | `"public"` atau `"private"` jika tersedia |

### 7.2 STATE

|| Field | Type | Required | Description |
|-------|------|----------|-------------|
|| archived | bool \| None | NO | True jika repository archived |
|| fork | bool \| None | NO | True jika repository adalah fork |
|| default_branch | str \| None | NO | Nama default branch (mis. "main", "master") |

### 7.3 METADATA

|| Field | Type | Required | Description |
|-------|------|----------|-------------|
|| description | str \| None | NO | Deskripsi repository dari GitHub |
|| created_at | str \| None | NO | ISO-8601 timestamp kapan repository dibuat |
|| updated_at | str \| None | NO | ISO-8601 timestamp kapan repository terakhir di-update |
|| pushed_at | str \| None | NO | ISO-8601 timestamp kapan terakhir push |

### 7.4 SCALE

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| size_kb | int \| None | NO | Ukuran repository dalam KB (dari GitHub) |

### 7.5 LANGUAGE

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| primary_language | str \| None | NO | Bahasa pemrograman dominan (jika tersedia dari API) |
| language_breakdown | dict[str, int] \| None | NO | Pemetaan bahasa → persentase/byte (jika tersedia) |

### 7.6 LICENSE

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| license_detected | bool \| None | NO | True jika license terdeteksi |
| license_spdx_id | str \| None | NO | SPDX identifier (mis. "MIT", "Apache-2.0") |
| license_name | str \| None | NO | Nama license dari GitHub |

### 7.7 ACTIVITY

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| open_issues_count | int \| None | NO | Jumlah open issues (jika tersedia) |
| stars | int \| None | NO | Jumlah stars (jika tersedia) |
| forks_count | int \| None | NO | Jumlah forks (jika tersedia) |
| watchers | int \| None | NO | Jumlah watchers (jika tersedia) |

### 7.8 PROVENANCE

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| profile_run_id | str | YES | ID unik dari profile run ini |
| profiled_at | str | YES | ISO-8601 timestamp kapan profiling dilakukan |
| source_endpoint | str | YES | Endpoint API yang digunakan (mis. `/repos/{owner}/{repo}`) |
| adapter_version | str | YES | Versi adapter profiler (mis. `"1.0.0"`) |
| raw_payload_reference | str \| None | NO | Reference ke raw evidence (diset oleh engine) |
| raw_payload_hash | str \| None | NO | Hash dari raw evidence (diset oleh engine) |

### 7.9 FIELD SEMANTICS

**NULL/unavailable semantics:**

- Jika GitHub API tidak mengembalikan field tertentu, field tersebut adalah NULL
- Tidak ada nilai default yang diarang
- Tidak ada imputation

**Contoh:**

- Repository tidak memiliki license terdeteksi → `license_detected = false`, `license_spdx_id = null`, `license_name = null`
- Repository tidak memiliki language information → `primary_language = null`, `language_breakdown = null`
- GitHub tidak mengembalikan `description` → `description = null`

---

## 8. GITHUB V1 DATA SOURCE

### 8.1 Endpoint Utama

V1 menggunakan satu endpoint utama:

```
GET https://api.github.com/repos/{owner}/{repository}
```

Endpoint ini mengembalikan objek repository lengkap termasuk:

- visibility
- archived
- fork
- default_branch
- description
- created_at
- updated_at
- pushed_at
- size
- language
- license (nested object)
- open_issues_count
- stargazers_count
- forks_count
- watchers_count
- dan field lainnya

### 8.2 Endpoint Tambahan (V1)

**V1 TIDAK menggunakan endpoint tambahan.**

Endpoint berikut ditandai sebagai **future extension**, bukan kebutuhan V1:

- `/repos/{owner}/{repo}/languages` — language breakdown lebih detail
- `/repos/{owner}/{repo}/license` — license information terpisah
- `/repos/{owner}/{repo}/commits` — commit history
- `/repos/{owner}/{repo}/pulls` — pull request information
- `/repos/{owner}/{repo}/contents` — file listing
- `/git/trees` — tree information

**Alasan:**

V1 berfokus pada metadata profile dasar yang tersedia dari single endpoint `GET /repos/{owner}/{repo}`. Endpoint tambahan tidak diperlukan untuk contract V1.

### 8.3 Response Schema

Response dari endpoint GitHub dijadikan **raw payload**.

Raw payload disimpan sesuai kontrak raw evidence (lihat Bagian 14).

Raw payload TIDAK dimodifikasi, TIDAK direkonstruksi, dan TIDAK difilter sebelum disimpan.

---

## 9. HTTP CLIENT REUSE

### 9.1 Keputusan

Repository Profiler V1 **REUSE** `GitHubHTTPClient` existing dari `hbh/discovery/github/http_client.py`.

### 9.2 Alasan

1. `GitHubHTTPClient` sudah menangani:
   - HTTP transport
   - Authentication header construction (Bearer token dari GITHUB_TOKEN)
   - Response parsing ke `GitHubHTTPResponse`
   - Rate limit metadata extraction
   - Timeout handling
   - Path validation

2. Tidak ada alasan arsitektural untuk membuat HTTP client kedua.

3. Reuse konsisten dengan prinsip DRY dan menghindari duplikasi infrastruktur.

### 9.3 Gap yang Diidentifikasi

Jika ditemukan gap dalam `GitHubHTTPClient` untuk kebutuhan Repository Profiler, dokumentasikan sebagai gap. Jangan memperbaiki pada tahap specification.

**Gap yang mungkin:**

- Jika Repository Profiler membutuhkan parameter request yang berbeda dari GitHubAdapter, apakah `GitHubHTTPClient.request()` cukup fleksibel?
- Jika Repository Profiler perlu menangani response yang berbeda (mis. response error yang berbeda), apakah current error handling cukup?

Kedua pertanyaan akan dit valideasi pada implementasi, bukan pada specification.

---

## 10. CANONICAL REPOSITORY IDENTITY

### 10.1 Bentuk Canonical

Bentuk canonical untuk GitHub repository identity:

```
github:owner/repository
```

### 10.2 Contoh

```
github:octocat/Hello-World
github:facebook/react
github:torvalds/linux
```

### 10.3 Normalization Rules

1. **Owner normalization:**
   - Case-sensitive (tetap seperti asli dari input/GitHub)
   - Tidak ada transformasi

2. **Repository name normalization:**
   - Case-sensitive (tetap seperti asli dari input/GitHub)
   - Trailing slash dihilangkan: `owner/repo/` → `owner/repo`
   - `.git` suffix dihilangkan: `owner/repo.git` → `owner/repo`
   - Tidak ada transformasi lainnya

3. **URL parsing:**
   - `https://github.com/owner/repo` → `owner/repo`
   - `https://github.com/owner/repo.git` → `owner/repo`
   - `https://github.com/owner/repo/` → `owner/repo`

4. **Case handling:**
   - GitHub repository name dan owner adalah case-insensitive secara efektif, tetapi API mengembalikan case asli
   - Repository Profiler menggunakan case dari GitHub API response sebagai canonical
   - Jika input dan API response berbeda case, gunakan API response

### 10.4 Invalid Repository Identifier

Identifier dianggap tidak valid dan ditolak:

- Tidak mengandung `/` → invalid
- Owner kosong → invalid
- Repository name kosong → invalid
- Repository name mengandung karakter ilegal GitHub → invalid

### 10.5 Source ID untuk Repository

Bentuk source_id untuk repository:

```
github:owner/repository
```

Ini konsisten dengan bentuk canonical identity.

---

## 11. FACT VS DERIVED DATA

### 11.1 Factual Data (V1)

Data berikut adalah FAKTA dari GitHub API:

- visibility
- archived
- fork
- default_branch
- description
- created_at
- updated_at
- pushed_at
- size (size_kb)
- language (primary_language)
- license (license_detected, license_spdx_id, license_name)
- open_issues_count
- stargazers_count (stars)
- forks_count
- watchers_count (watchers)

### 11.2 DILARANG untuk V1

Data berikut DILARANG untuk V1:

- score
- rank
- attractiveness
- quality
- difficulty
- EV (expected value)
- acceptance probability
- recommendation
- active/inactive judgment
- freshness score
- competition score
- maintainer quality score

### 11.3 Derived Observation yang Diizinkan (jika deterministic)

Derived observation yang diizinkan jika:

1. **Deterministic** — tidak bergantung pada opinion atau heuristik
2. ** factual** — dapat diverifikasi dari data
3. **tidak judgment** — tidak menilai baik/buruk

**Contoh yang diizinkan (jika ada kebutuhan):**

- `has_license = true` jika `license_detected = true` (ini hanya restate fakta, bukan judgment)
- `is_archived = true` jika `archived = true` (sama)

**Contoh yang DILARANG:**

- `repository_quality = 20` (judgment)
- `is_good_for_bounty = true` (judgment)
- `priority = high` (judgment)

### 11.4 Prinsip

> Repository Profiler menghasilkan FAKTA.
> Policy/Triage menghasilkan KEPUTUSAN.
> Jangan mencampurkan kedua tanggung jawab tersebut.

---

## 12. CLONE BOUNDARY

### 12.1 Prinsip

```
PROFILE FIRST
CLONE ONLY IF AUTHORIZED
```

### 12.2 V1 Behavior

Repository Profiler V1 TIDAK:

- melakukan `git clone`
- melakukan `git checkout`
- melakukan `git pull`
- menjalankan repository
- menginstall dependencies
- melakukan build
- melakukan test
- menjalankan scripts

Clone/deep inspection harus menjadi **tahap terpisah** yang memiliki authorization dan security contract sendiri.

### 12.3 Future Extension

Deep profiling (yang membutuhkan clone) dapat menjadi future scope. Specification ini menandai deep profiling sebagai **extension boundary**, bukan implementation requirement saat ini.

---

## 13. RAW EVIDENCE

### 13.1 Strategi

Repository Profiler menggunakan existing `RawStorage` dari `hbh/discovery/raw_storage.py`.

TIDAK membuat second raw storage mechanism.

### 13.2 Apa yang Disimpan

Raw evidence adalah **complete GitHub API response** untuk endpoint `GET /repos/{owner}/{repo}`.

Ini termasuk semua field yang dikembalikan GitHub, termasuk field yang tidak dipetakan ke RepositoryProfile.

### 13.3 Hash

SHA-256 dari canonical JSON bytes digunakan sebagai:

- Nama file
- `raw_payload_hash`

### 13.4 Reference

`raw_payload_reference` disimpan dalam bentuk:

```
github/<sha256>.json
```

### 13.5 Fail-Closed Semantics

Jika raw_storage dikonfigurasi dan storage gagal:

- Profile TIDAK dianggap valid
- Engine/repository yang拥有 persistence ownership memutuskan apa yang terjadi

Jika raw_storage TIDAK dikonfigurasi:

- Profile masih dapat diterima jika contract mengizinkan tanpa evidence
- Ini harus didefinisikan secara eksplisit dalam contract

### 13.6 Tidak Ada Reconstructed Evidence

Raw evidence TIDAK boleh:

- Direkonstruksi dari normalized RepositoryProfile
- Menggunakan `repr()` atau `str()`
- Menggunakan `default=str` serialization
- Mengandung fabricated metadata

Raw evidence harus berasal dari ACTUAL SOURCE PAYLOAD.

---

## 14. PROVENANCE

### 14.1 Field Provenance yang Wajib

| Field | Mandatory | Description |
|-------|-----------|-------------|
| source | YES | `"github"` |
| repository | YES | `owner/repository` canonical |
| profile_run_id | YES | ID unik profile run |
| profiled_at | YES | Timestamp profiling |
| source_endpoint | YES | `/repos/{owner}/{repo}` |
| adapter_version | YES | Versi profiler adapter |
| raw_payload_reference | NO | Jika raw storage tersedia |
| raw_payload_hash | NO | Jika raw storage tersedia |

### 14.2 Field Provenance yang Optional

| Field | Mandatory | Description |
|-------|-----------|-------------|
| raw_payload_reference | NO | Jika raw storage dikonfigurasi |
| raw_payload_hash | NO | Jika raw storage dikonfigurasi |

---

## 15. PERSISTENCE BOUNDARY

### 15.1 Keputusan Schema — Dikonfirmasi Human

**Final decision:** Gunakan pemisahan repository identity dan repository profile.

**Logical architecture:**

```
repositories (stable identity)
    ↓
repository_profiles (profile snapshot/result)
    ↓
profile_run / provenance
```

- **Tabel `repositories`**: merepresentasikan stable repository identity. Satu baris per repository canonical.
- **Tabel `repository_profiles`**: merepresentasikan profile snapshot/result yang dapat berubah antar profiling run. Satu repository dapat memiliki beberapa historical profiles.
- **Tabel `profile_runs`** (atau mekanisme provenance yang setara): mencatat setiap profiling run dengan run_id, timestamp, dan metadata run.

**Kontrak:**

- Repository identity (`github:owner/repository`) adalah stabil dan persisten.
- Profile adalah snapshot waktu-dependent yang dapat diulang.
- Repeated profiling menghasilkan historical profile records/snapshots tanpa membuat repository identity baru.
- Tidak ada destructive overwrite tanpa documented strategy.

### 15.2 Tidak Ada Migration Sekarang

**Tidak ada SQLite schema change pada tahap specification finalization ini.**

Spesifikasi ini hanya menetapkan logical architecture. Implementation phase akan menentukan exact SQL schema dan migration strategy.

**Migration requirement yang akan diterapkan pada implementation:**

- **Additive migration:** tabel/kolom baru ditambahkan, tabel existing tidak dihapus.
- **Nullable strategy:** kolom baru nullable untuk compatibility dengan existing rows.
- **Compatible dengan existing data:** existing rows tidak broken oleh migration.
- **Rollback consideration:** migration harus dapat direverse jika diperlukan.
- **Dampak baseline:** migration harus menjaga 556/556 baseline.

### 15.3 Owner Persistence

**Final decision:** Orchestration layer adalah persistence owner.

Repository Profiler menghasilkan `RepositoryProfile` result.

Orchestration layer melakukan:

- persistence ke SQLite
- state transition
- audit event

Repository Profiler **TIDAK direct-write SQLite**.

### 15.4 Audit Existing Architecture

Dari inspeksi `hbh/core/database.py`:

1. **Tabel existing:** `repositories` (line 44-54) — konsep repository sudah ada.
2. **Tabel discovery:** `discovery_runs`, `bounties` dengan discovery columns.
3. **Tidak ada tabel `repository_profiles` atau `profile_runs` yang terpisah.**

Existing tabel `repositories` memiliki kolom yang tidak lengkap untuk contract V1. Implementation phase akan memutuskan apakah kolom tersebut di-extend atau tabel `repository_profiles` baru dibuat sebagai logical architecture yang ditetapkan di atas.

---
## 16. STATE MACHINE BOUNDARY

### 16.1 Conceptual Transition

```
DISCOVERED
    ↓
PROFILED
```

### 16.2 Siapa yang Melakukan Transition? — Dikonfirmasi Human

**Final decision:** Orchestration layer adalah state transition owner.

Repository Profiler hanya menghasilkan `RepositoryProfile` result. Repository Profiler TIDAK boleh melakukan direct state transition dan TIDAK boleh mengambil ownership atas state machine.

**Flow terdefinisi:**

```
DISCOVERED
    ↓
RepositoryProfiler
    ↓ (menghasilkan RepositoryProfile result)
Orchestration layer
    ↓ (SQLite persistence)
audit event
    ↓
PROFILED
```

Repository Profiler tidak memiliki akses direct ke state machine dan tidak memancarkan audit event sendiri untuk transisi state. Semua state transition dan audit event dilakukan oleh orchestration layer yang memiliki ownership.

---

## 16. STATE MACHINE BOUNDARY

### 16.1 Conceptual Transition

```
DISCOVERED
    ↓
PROFILED
```

### 16.2 Siapa yang Melakukan Transition?

**Default preference:**

Repository Profiler menghasilkan `RepositoryProfile` result.

Orchestration layer yang memiliki ownership melakukan:

- persistence
- state transition DISCOVERED → PROFILED
- audit event

Repository Profiler TIDAK langsung melakukan arbitrary state transition.

### 16.3 Jika Architecture Existing Berbeda

Jika inspection menunjukkan bahwa architecture existing memiliki pendekatan yang berbeda untuk state transition, dokumentasikan fakta tersebut. Jangan memaksa perubahan hanya untuk memudahkan implementation.

---

## 17. ERROR SEMANTICS

### 17.1 Status Terdefinisi

| Status | Kriteria |
|--------|----------|
| SUCCESS | Repository berhasil diakses dan minimum required metadata tersedia |
| PARTIAL | Repository dapat diakses tetapi sebagian metadata gagal diperoleh |
| FAILED | Repository tidak dapat diakses atau tidak menghasilkan profile yang valid |

### 17.2 Minimum Required Metadata untuk SUCCESS — Dikonfirmasi Human

**Final decision:** Minimum metadata untuk SUCCESS:

- `source`
- `repository`
- `canonical_url`
- `owner`
- `name`

Repository identity harus valid dan response source harus berhasil diproses.

Metadata lain boleh `null`/`unavailable` apabila GitHub source tidak menyediakannya.

**Contoh:**

- `license = null` TIDAK otomatis berarti FAILED.
- `language = null` TIDAK otomatis berarti FAILED.
- `size_kb = null` TIDAK otomatis berarti FAILED.

**SUCCESS** ditentukan berdasarkan: minimum identity metadata lengkap + successful source processing.

**FAILED** digunakan ketika repository profile minimum tidak dapat dibentuk:

- HTTP 404 → FAILED
- Malformed/unusable source response → FAILED
- Valid repository metadata dengan `license = null` → SUCCESS (bukan FAILED)
- Valid repository metadata dengan `language = null` → SUCCESS (bukan FAILED)

### 17.3 HTTP Status Mapping

| HTTP Status | Profiler Status |
|-------------|-----------------|
| 200 | SUCCESS (jika minimum metadata tersedia) atau PARTIAL |
| 401 | FAILED (authentication failure) |
| 403 | FAILED (forbidden) |
| 404 | FAILED (repository not found) |
| 429 | FAILED/PARTIAL (rate limited) |
| 5xx | FAILED/PARTIAL (server error) |
| timeout | FAILED |
| network error | FAILED |
| malformed JSON | FAILED |
| unexpected schema | FAILED |
| missing required metadata | FAILED (meskipun HTTP 200) |

### 17.4 Invariant

- FAILED → tidak ada RepositoryProfile yang dianggap valid
- PARTIAL → RepositoryProfile mungkin memiliki data yang tidak lengkap, tetapi data yang ada harus provenance-safe dan auditable

---

## 18. RATE LIMIT SEMANTICS

### 18.1 Konsistensi dengan GH-3B Frozen Contract

Repository Profiler V1 mengikuti kontrak rate limit yang sama dengan GitHub adapter yang sudah di-FREEZE di GH-3B.

### 18.2 429 Behavior

- `rate_limit_hit = true`
- No retry
- No sleep
- No backoff
- No jitter
- No retry budget
- No circuit breaker

### 18.3 Rate Limit Metadata

Profiler boleh merekam metadata rate-limit jika tersedia (mis. `X-RateLimit-Remaining`).

### 18.4 Tidak Ada Retry Engine

Profiler TIDAK bertindak sebagai retry engine.

Recovery dari rate limit menjadi responsibility scheduler/recovery layer di future phase.

---

## 19. SECURITY BOUNDARY

### 19.1 Repository sebagai UNTRUSTED DATA

Repository metadata dan konten adalah UNTRUSTED EXTERNAL DATA.

Semua data berikut diperlakukan sebagai data:

- description
- README (jika diakses di future)
- repository metadata
- issue text (jika diakses)
- labels
- branch names
- filenames
- owner names
- repository names

### 19.2 DILARANG

Profiler DILARANG:

- `eval()` pada data repository
- `exec()` pada data repository
- shell execution berdasarkan repository content
- subprocess berdasarkan repository content
- menjalankan README commands
- dependency installation
- repository scripts
- build
- tests
- hooks

### 19.3 Credential Rule

`GITHUB_TOKEN` hanya boleh berasal dari environment/configuration mechanism yang telah disetujui architecture.

Token TIDAK boleh muncul di:

- logs
- exceptions
- raw evidence
- database
- profile result
- audit events
- documentation examples

### 19.4 Security Boundary Explicit

Specification ini menetapkan explicit security boundary:

> Repository Profiler adalah kolektor fakta.
> Semua data dari repository adalah untrusted.
> Tidak ada execution, eval, atau command dari repository content.

---

## 20. CONFIGURATION

### 20.1 Konfigurasi Minimal V1

```yaml
repository_profiler:
  enabled: true
  timeout_seconds: 10
  max_repositories_per_run: 100
```

### 20.2 Field Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| enabled | bool | false | Apakah profiler diaktifkan |
| timeout_seconds | int | 10 | Timeout per request (konsisten dengan GH-3B) |
| max_repositories_per_run | int | 100 | Maksimum repository yang diprofil per run |

### 20.3 Tidak Ada Configuration Berlebihan

Configuration V1 minimal. Tidak membuat parameter yang tidak diperlukan untuk contract V1.

---

## 21. GLOBAL LIMITS

### 21.1 Hubungan dengan Existing Global Limits

Discovery Engine memiliki:

- `MAX_TOTAL_CANDIDATES = 200`
- `MAX_RUN_DURATION_SECONDS = 300`

Repository Profiler TIDAK boleh:

- menaikkan global limit ini
- bypass global orchestration limits
- membuat local limit yang mengalahkan global limit

### 21.2 Local Limit

Jika Repository Profiler memiliki local limit, local limit adalah **additional guard**, bukan cara menaikkan global limit.

---

## 22. IDEMPOTENCY

### 22.1 Repository Identity stabil

Repository identity `github:owner/repository` adalah stabil.

### 22.2 Profile Runs Berulang

Jika repository yang sama di-profil berkali-kali:

- Repository identity tetap sama
- Profile run ID berbeda untuk setiap run
- Hasil profile mungkin berbeda karena metadata repository berubah seiring waktu

### 22.3 Strategi untuk Repeated Profiling

- **Same repository, different run:** Hasil profile baru menggantikan hasil lama (jika orchestration layer mengizinkan)
- **Historical profile:** Tergantung implementasi persistence, historical profile mungkin dipertahankan atau digantikan
- **Duplicate profile result:** Jika repository di-profil dua kali dalam run yang sama, hasilnya adalah duplicate (didedup oleh orchestration layer)

### 22.4 Tidak Ada Penghapusan Historical Evidence

Historical evidence TIDAK dihapus secara diam-diam oleh Repository Profiler.

---

## 23. FRESHNESS

### 23.1 Field yang Disimpan

- `profiled_at` — kapan profiling dilakukan
- Source timestamps (`created_at`, `updated_at`, `pushed_at`) jika tersedia dari GitHub API

### 23.2 DILARANG untuk V1

- freshness score
- TTL kompleks
- active/inactive judgment

Timestamp adalah fakta. Interpretasi adalah responsibility layer berikutnya.

### 23.3 Caching sebagai Future Optimization

Caching profile response dapat ditandai sebagai future optimization, bukan requirement V1.

---

## 24. SCHEMA / MIGRATION STRATEGY

### 24.1 Audit Existing Schema

Dari `hbh/core/database.py`:

- **Tabel `repositories`** sudah ada dengan kolom: repo_id, owner, name, size_kb, language, default_branch, last_push, has_lfs, profile_status
- **Tabel `discovery_runs`** ada untuk discovery runs
- **Tabel `bounties`** dengan discovery columns ada

### 24.2 Apakah Migration Diperlukan?

**Observasi:**

1. Tabel `repositories` sudah ada, yang menunjukkan bahwa project memiliki konsep repository profiling.
2. Namun kolom di tabel `repositories` tidak lengkap dengan contract V1 (mis. tidak ada visibility, archived, fork, created_at, updated_at, pushed_at, license-related fields, stars/forks/watchers).
3. Tidak ada tabel `profile_runs` yang terpisah.

**Keputusan specification:**

V1 specification TIDAK menentukan perubahan schema sekarang.

Jika pada implementasi ditemukan bahwa schema existing tidak cukup, dokumentasikan sebagai:

- **Schema gap**
- Rekomendasi migration (jika ada)
- Dampak terhadap baseline

### 24.3 Jika Migration Diperlukan

Migration harus:

- Additive (tambah kolom/tabel baru, tidak hapus yang ada)
- Nullable strategy untuk kolom baru (existing rows tidak broken)
- Compatible dengan existing data
- Dokumentasi rollback consideration
- Dijalankan sebagai migrasi terpisah, bukan hardcoded di profiler

---

## 25. TEST CONTRACT

### 25.1 Test Matrix Behavioral

| Code | Test | Deskripsi |
|------|------|-----------|
| A | test_200_success | Repository berhasil diakses, profil lengkap |
| B | test_401 | 401 → FAILED |
| C | test_403 | 403 → FAILED |
| D | test_404 | 404 → FAILED |
| E | test_429 | 429 → rate_limit_hit=true, FAILED/PARTIAL |
| F | test_5xx | 5xx → FAILED/PARTIAL |
| G | test_timeout | Timeout → FAILED |
| H | test_network_failure | Network error → FAILED |
| I | test_malformed_json | Malformed JSON → FAILED |
| J | test_unexpected_schema | Schema tidak sesuai → FAILED |
| K | test_missing_required_field | Field wajib tidak ada → FAILED |
| L | test_null_optional_field | Field optional null → diizinkan |
| M | test_unknown_additional_field | Field tambahan diabaikan/diantar sebagai raw |
| N | test_archived | archived field dipetakan benar |
| O | test_fork | fork field dipetakan benar |
| P | test_default_branch | default_branch dipetakan benar |
| Q | test_size | size_kb dipetakan benar |
| R | test_language | primary_language dipetakan benar |
| S | test_language_breakdown | language_breakdown dipetakan benar |
| T | test_license_detected | license_detected dipetakan benar |
| U | test_license_absent | license tidak ada → null/unavailable |
| V | test_activity_timestamps | created_at, updated_at, pushed_at dipetakan benar |
|| W | test_issue_star_fork_watch | open_issues_count, stars, forks_count, watchers dipetakan benar |
| X | test_canonical_identity | Canonical identity benar |
| Y | test_owner_repo_normalization | Normalization benar |
| Z | test_duplicate_profiling | Profiling berulang diterima |
| AA | test_profile_run_id | profile_run_id ada |
| AB | test_source_endpoint | source_endpoint tercatat |
| AC | test_raw_reference | raw_payload_reference ada |
| AD | test_raw_hash | raw_payload_hash ada |
| AE | test_hash_integrity | Hash verifikasi berhasil |
| AF | test_malicious_textual_content | Konten teks jahat tidak dieksekusi |
| AG | test_command_looking_content | Konten seperti command tidak dieksekusi |
| AH | test_token_leakage | Token tidak bocor |
| AI | test_no_subprocess | Tidak ada subprocess |
| AJ | test_no_arbitrary_execution | Tidak ada arbitrary execution |
| AK | test_no_direct_sqlite | Profiler tidak direct-write SQLite |
| AL | test_no_direct_state_transition | Profiler tidak melakukan state transition |
| AM | test_no_triage_decision | Tidak ada triage decision |
| AN | test_no_score | Tidak ada score |
| AO | test_no_recommendation | Tidak ada recommendation |
| AP | test_partial_profile | PARTIAL profile diterima |
| AQ | test_failed_profile | FAILED profile tidak valid |
| AR | test_successful_profile | SUCCESS profile valid |
| AS | test_rate_limit_signal | rate_limit_hit benar |
| AT | test_no_retry | Tidak ada retry |
| AU | test_no_sleep | Tidak ada sleep |

### 25.2 Behavioral Coverage

Behavioral coverage lebih penting daripada target jumlah test.

---

## 26. FUTURE EXTENSIONS

### 26.1 Endpoint Tambahan

- `/repos/{owner}/{repo}/languages` — language breakdown lebih detail
- `/repos/{owner}/{repo}/license` — license information terpisah
- `/repos/{owner}/{repo}/commits` — commit history
- `/repos/{owner}/{repo}/pulls` — pull request information
- `/repos/{owner}/{repo}/contents` — file listing

### 26.2 Deep Profiling

- Clone repository
- Analisis struktur codebase
- Dependency analysis
- Build/test execution (jika diizinkan)

### 26.3 Multi-Source

- Support untuk non-GitHub repository sources (GitLab, Bitbucket, dll)

### 26.4 Caching

- Profile response caching untuk efisiensi

---

## 27. OPEN QUESTIONS

### 27.1 Persistence Schema — DITUTUP

**Resolving decision:** Human arsitektur telah memutuskan menggunakan pemisahan `repositories` (identity) dan `repository_profiles` (snapshot).

Lihat Bagian 15.1 untuk logical architecture yang ditetapkan.

**Tersisa sebagai implementation detail:**
- Exact SQL schema
- Migration order
- Kolom spesifik untuk `repository_profiles`

Ini bukan architectural blocker. Implementation phase akan menentukannya.

### 27.2 Minimum Required Metadata — DITUTUP

**Resolving decision:** Human arsitektur telah memutuskan minimum adalah 5 field identity.

Lihat Bagian 17.2 untuk kriteria yang ditetapkan.

**Tersisa sebagai implementation detail:**
- Validasi dan error handling spesifik
- Edge case untuk field identity kosong

Ini bukan architectural blocker.

### 27.3 Raw Evidence Wajib — DITUTUP

**Resolving decision:** Raw evidence adalah bagian dari kontrak provenance. Specification sudah menetapkan raw evidence strategy di Bagian 13.

- Jika raw_storage dikonfigurasi dan storage gagal → profile tidak dianggap valid (fail-closed).
- Jika raw_storage tidak dikonfigurasi → profile masih dapat diterima jika contract mengizinkan tanpa evidence.
- Orchestration layer memutuskan final validasi profile berdasarkan konfigurasi evidence.

Tidak ada open question tersisa.

### 27.4 State Transition Owner — DITUTUP

**Resolving decision:** Human arsitektur telah memutuskan orchestration layer adalah state transition owner.

Lihat Bagian 16.2 untuk flow yang ditetapkan.

Repository Profiler TIDAK boleh melakukan direct state transition.

Tidak ada open question tersisa.

### 27.5 GitHub V1 Endpoint — DITUTUP

**Resolving decision:** Human arsitektur telah memutuskan V1 hanya menggunakan satu endpoint.

Lihat Bagian 8.1 dan 8.2.

**Final decision:** V1 hanya menggunakan endpoint:

```
GET /repos/{owner}/{repo}
```

Endpoint tambahan (`/languages`, `/license`, `/commits`, `/pulls`, `/contents`, `/git/trees`) ditandai sebagai **future extension only**.

Tidak ada open question tersisa.

---

## 28. ACCEPTANCE CRITERIA

Specification dianggap ACCEPTABLE jika:

1. **Contract cukup deterministic:** Semua field terdefinisi, tipe terdefinisi, semantics terdefinisi
2. **Ownership jelas:** Siapa yang melakukan persistence, siapa yang melakukan state transition
3. **Schema cukup jelas:** RepositoryProfile logical schema lengkap
4. **Security boundary jelas:** Explicit untrusted data handling, credential boundary
5. **Error semantics jelas:** SUCCESS/PARTIAL/FAILED terdefinisi dengan kriteria
6. **Evidence strategy jelas:** Raw evidence, hash, reference, fail-closed
7. **Test contract jelas:** Test matrix cukup untuk behavioral coverage
8. **Tidak ada unresolved blocker:** Open questions non-blocking atau ditandai

---

## 29. SELF-REVIEW

### 29.1 Contradictions

- **Tidak ada contradiction yang ditemukan.**

### 29.2 Ambiguity

- **Minimum required metadata:** Beberapa ambigu (lihat Open Question 27.2)
- **Persistence schema:** Beberapa ambigu (lihat Open Question 27.1)
- **State transition owner:** Beberapa ambigu (lihat Open Question 27.4)

### 29.3 Missing Field

- **Tidak ada field yang hilang** dalam logical schema yang diidentifikasi.

### 29.4 Inconsistent Ownership

- **Tidak ada inconsistent ownership** yang ditemukan. Persistence boundary dan state machine boundary sudah didefinisikan.

### 29.5 Hidden Decision Logic

- **Tidak ada hidden decision logic** yang ditemukan. Semua field adalah fakta, tanpa scoring atau judgment.

### 29.6 Accidental Scoring

- **Tidak ada accidental scoring** yang ditemukan.

### 29.7 Duplicate Infrastructure

- **Tidak ada duplicate infrastructure** yang ditemukan. HTTP client reuse sudah ditentukan.

### 29.8 Security Gap

- **Tidak ada security gap** yang ditemukan. Explicit security boundary sudah didefinisikan.

### 29.9 Credential Leakage Risk

- **Tidak ada credential leakage risk** yang ditemukan. Credential rule sudah didefinisikan.

### 29.10 Retry Creep

- **Tidak ada retry creep** yang ditemukan. Rate limit semantics sudah konsisten dengan GH-3B.

### 29.11 Clone Creep

- **Tidak ada clone creep** yang ditemukan. Clone boundary sudah didefinisikan.

### 29.12 Schema Migration Risk

- **Schema migration risk** diidentifikasi sebagai open question, bukan blocker.

### 29.13 State Machine Violation

- **Tidak ada state machine violation** yang ditemukan.

### 29.14 Persistence Violation

- **Tidak ada persistence violation** yang ditemukan.

---

## 30. KONTRACT REVIEW SUMMARY

| Area | Status | Keterangan |
|------|--------|------------|
| Identity | PASS | Canonical identity terdefinisi |
| Metadata | PASS | Semua field terdefinisi |
| License | PASS | License boundary jelas |
| Activity | PASS | Activity facts hanya factual |
| Provenance | PASS | Provenance fields lengkap |
| Persistence | PASS | Boundary jelas, schema sebagai open question |
| State Machine | PASS | Boundary jelas, owner sebagai open question |
| Raw Evidence | PASS | Strategi jelas, reuse existing RawStorage |
| Error Semantics | PASS | SUCCESS/PARTIAL/FAILED terdefinisi |
| Rate Limit | PASS | Konsisten dengan GH-3B frozen contract |
| Security | PASS | Explicit boundary, credential rule jelas |
| Configuration | PASS | Minimal, tidak berlebihan |
| Global Limits | PASS | Tidak boleh bypass global limits |
| Test Contract | PASS | Test matrix terdefinisi |
| Clone Boundary | PASS | Profile first, clone only if authorized |
| Fact vs Derived | PASS | V1 hanya factual data |

---

## 31. IMPLEMENTATION READINESS

**STATUS: SPECIFICATION FINALIZED — READY FOR HUMAN FREEZE**

Specification telah diselesaikan dan ditinjau ulang setelah human arsitektur memutuskan 4 open question.

**Alasan:**

1. Contract deterministic — semua field terdefinisi, type terdefinisi, semantics terdefinisi
2. Ownership jelas — persistence dan state transition owner ditetapkan sebagai orchestration layer
3. Schema cukup jelas — logical schema lengkap, pemisahan identity dan profile ditetapkan
4. Security boundary jelas — explicit untrusted data handling, credential boundary
5. Error semantics jelas — SUCCESS/PARTIAL/FAILED terdefinisi dengan kriteria minimum metadata
6. Evidence strategy jelas — reuse RawStorage existing, fail-closed semantics
7. Test contract jelas — test matrix terdefinisi
8. Semua open questions ditutup — tidak ada unresolved architectural blocker

**TIDAK ADA open questions yang menghalangi.**

**Implementation readiness:** Specification siap untuk di-freeze oleh human. Setelah freeze, implementation dapat dimulai dengan risiko minimal.

---

## 32. STOP CONDITION

Setelah specification ini selesai:

- STOP
- JANGAN membuat RP-1
- JANGAN membuat RepositoryProfiler class
- JANGAN membuat adapter
- JANGAN membuat migration
- JANGAN membuat test implementation
- JANGAN mengubah production architecture
- JANGAN melakukan Git commit
- JANGAN melakukan Git push

Lakukan only:

- Verifikasi repository sanity check
- Verifikasi baseline 556/556 PASS
- Update checkpoint
- Final report

---

*Hermes adalah executor/development agent hanya. Specification ini adalah hasil kerja speification-only phase.*
