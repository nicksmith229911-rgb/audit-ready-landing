# ENGINEER ONBOARDING BRIEF
**Project:** AuditReady AI — Triple-Engine Consensus Pipeline v4.0
**Prepared For:** Ivan (Senior AI Architect)
**Date:** 2026-03-16
**Last Verified:** March 2026
**Classification:** Internal Technical — No Secrets Included

---

## 1. System Architecture Flow

The pipeline has **four ordered stages**. Each stage gates the next; a failure at any stage kills the run and marks the scan record as `failed` in Supabase.

```
┌─────────────────────────────────────────────────────────────────────────┐
│  STAGE 1: INGEST                                                        │
│  User uploads PDF / DOCX / TXT via Dashboard.tsx (≤10 MB).             │
│  File is validated, stored in Supabase Storage bucket "scans",         │
│  and a "pending" scan record is inserted into the `scans` table.       │
└────────────────────────┬────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STAGE 2: DOCUMENT AI (OCR)                                             │
│  A Supabase database trigger fires on the new scan record and calls    │
│  Google Document AI to extract structured text from the uploaded file. │
│  Extracted text is written to the `audit_results` table                │
│  (FK: audit_results.scan_id → scans.id).                               │
└────────────────────────┬────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STAGE 3: THE JURY  (Triple-Engine Consensus)                           │
│  Three AI models analyse the extracted text concurrently via           │
│  asyncio.gather() (Python) / Promise.all() (JS):                       │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ Juror A — Claude Opus 4.6   (Lead / Legal)                       │  │
│  │   Endpoint: Global Vertex AI → AnthropicVertex SDK               │  │
│  │   Auth: rawPredict with OAuth2 Bearer; anthropic-version header  │  │
│  │                                                                  │  │
│  │ Juror B — Gemini 3 Flash   (Technical / Speed)                   │  │
│  │   Endpoint: us-east5 → streamGenerateContent                     │  │
│  │   Auth: OAuth2 service-account token                             │  │
│  │                                                                  │  │
│  │ Juror C — Llama 4 Maverick  (Independent Wildcard)               │  │
│  │   Endpoint: us-east1 → MaaS OpenAPI chat/completions             │  │
│  │   Auth: Same OAuth2 token; OpenAI-compatible payload             │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  Each juror returns: risk_level, confidence, issues[], analysis.        │
│  _generate_consensus_report() aggregates by majority risk vote         │
│  and computes agreement_score (0.0 – 1.0).                             │
└────────────────────────┬────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STAGE 4: THE JUDGE  (Gemini 3.1 Pro via Vertex AI)                    │
│                                                                         │
│  ► QUALITATIVE ARBITER — not a weighted math formula.                  │
│                                                                         │
│  The Judge is invoked ONLY when a ≥15-point score discrepancy          │
│  exists between any two Jury members. It ingests all three Jury        │
│  reports plus the original document (up to max_tokens: 8192) and      │
│  renders a semantic verdict through contextual legal reasoning.        │
│                                                                         │
│  It does NOT average scores. It reads the actual compliance claims,    │
│  identifies which Juror provided stronger evidentiary support, and     │
│  issues a binding override. The 6-part executive deliverable is then   │
│  enforced via strict JSON Schema validation before persistence.        │
└────────────────────────┬────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STAGE 5: PERSISTENCE + REPORT                                          │
│  Final verdict written to Supabase (`scans` updated: compliance_score, │
│  status = "completed", is_safe, audit_log, evidence).                   │
│  Dashboard.tsx realtime listener (supabase.channel postgres_changes)   │
│  picks up the UPDATE event and triggers certificate.ts PDF generation  │
│  (jsPDF) client-side. User downloads the signed Audit Certificate.     │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Current State of Code

### 2.1 `orchestrator.py` + `jury_logic.js` — Async Integration

Both files implement the same logical pattern across Python (backend runner) and JavaScript (SDK client layer).

**Python (`orchestrator.py`):**
- `AIJuror` base class wraps a single model endpoint. Each juror holds a live `google.oauth2.service_account.Credentials` object that auto-refreshes via `get_valid_headers()` before every call (5-minute pre-expiry buffer).
- `TripleAuditOrchestrator.run_triple_audit()` fans out to all three jurors concurrently using `asyncio.gather(*tasks, return_exceptions=True)`. Exceptions are caught per-task; partial success is tolerated.
- `_generate_consensus_report()` performs majority-vote risk aggregation and surfaces the top-5 recurring issue types by frequency.

**JavaScript (`jury_logic.js`):**
- `JuryLogic` class maintains two `AnthropicVertex` SDK clients: a `global` client for Claude (routes to the Global endpoint) and a `regional` client scoped to `us-east5` for Gemini and Llama.
- `analyzeDocumentWithResilience()` dispatches to `analyzeWithAnthropicSDK()` for Anthropic models and `analyzeDocument()` (axios + raw Vertex REST) for Google/Meta models.
- EU failover: on a 429 on attempt 0 for Claude, `analyzeWithEUFailover()` instantiates a fresh `AnthropicVertex` client pointed at `europe-west1` and retries.

### 2.2 JSON Schema Enforcement — 6-Part Executive Deliverable

The Judge's output must conform to a strict 6-part schema before it is accepted downstream:

| Field | Type | Description |
|---|---|---|
| `executive_summary` | string | Plain-language verdict for non-technical stakeholders |
| `risk_level` | enum | `Low` / `Medium` / `High` / `Critical` |
| `compliance_score` | integer (0–100) | Authoritative score overriding Jury averages |
| `key_findings` | array[string] | Discrete compliance gaps identified |
| `action_plan` | array[string] | Ordered remediation steps (Top 3 minimum) |
| `confidence` | float (0.0–1.0) | Judge's self-assessed certainty |

Any response that fails schema validation is rejected and the orchestrator marks the run as `failed`. There is no silent fallback to an invalid partial result at this stage.

### 2.3 Supabase Schema — `judge_reports` + `scans` Link

The current migration set establishes the following relevant objects:

- **`scans` table** — Master record per uploaded file. Columns: `id (UUID PK)`, `user_id`, `file_name`, `file_url`, `storage_path`, `storage_bucket`, `status`, `compliance_score`, `is_safe`, `audit_log (JSONB)`, `evidence`.
- **`audit_results` table** (`20240302_create_audit_results.sql`) — Stores Document AI OCR output. References `scans(id)` via FK with `ON DELETE CASCADE`. Three RLS policies restrict SELECT / INSERT / UPDATE to the record's owning `user_id`.
- **`judge_reports` table** *(pending migration)* — Intended to store the full 6-part Judge deliverable, keyed to `scan_id`. Links to `scans` identically to `audit_results`. RLS mirrors the same user-isolation pattern.
- **Supabase client** in `orchestrator.py` is initialised with the **Service Role Key** (bypasses RLS) for backend writes, while the frontend uses the Publishable Anon Key.

### 2.4 Frontend — `Dashboard.tsx` State Mapping + `certificate.ts` PDF

`Dashboard.tsx` (`src/components/Dashboard.tsx`) manages the full scan lifecycle through a React state machine:

| State Variable | Type | Purpose |
|---|---|---|
| `scanStage` | `"uploading" \| "analyzing" \| "saving" \| null` | Drives progress-bar label |
| `scanProgress` | `number` (0–100) | Visual percentage |
| `activeScanId` | `string \| null` | FK to current `scans` row in flight |
| `isScanning` | `boolean` | Blocks concurrent uploads |

Key events:
1. **Upload** → `supabase.storage.from('scans').upload()` → stores file at `{scanRecordId}/{fileName}`.
2. **Analysis trigger** → `POST /functions/v1/audit-engine` via Supabase Edge Function.
3. **Real-time completion** → `supabase.channel('schema-db-changes')` listens for `UPDATE` on `scans WHERE id = {scanRecordId}`. When `status === 'completed'`, the UI unlocks the Download Certificate button.
4. **Certificate** → `generateCertificate()` in `src/lib/certificate.ts` renders a branded jsPDF document including: file name, compliance score, COMPLIANT / NON-COMPLIANT verdict, date, and a short `Certificate ID` derived from the first 8 chars of `scan.id`. Saved locally as `audit-certificate-{filename}.pdf`.

---

## 3. The Quota Blocker & Infrastructure (429 Errors)

### 3.1 Target Regions

| Model | Primary Region | Failover Region | Endpoint Type |
|---|---|---|---|
| Claude Opus 4.6 | `global` (AnthropicVertex SDK) | `europe-west1` | rawPredict |
| Gemini 3 Flash (Juror) | `us-east5` | `us-central1` *(manual override)* | streamGenerateContent |
| Llama 4 Maverick | `us-east5` | — | MaaS OpenAPI |
| **Gemini 3.1 Pro (Judge)** | **`us-east5`** | **`us-central1`** | **generateContent** |

> **Note:** `us-east5` is the designated production region for the Jury's Google/Meta workloads and is also where the Judge runs. `us-central1` is the documented fallover for quota exhaustion events.

### 3.2 Token Footprint — Why the Judge Hits Limits

The Judge is the heaviest consumer in the pipeline by design:

```
Input to Judge =
    Original document text
  + Jury Report A  (Claude Opus 4.6)   ~2 000 tokens
  + Jury Report B  (Gemini 3 Flash)    ~1 500 tokens
  + Jury Report C  (Llama 4 Maverick)  ~1 500 tokens
  + System prompt + schema instruction ~500  tokens
  ─────────────────────────────────────────────────
  Total Input (document-dependent)    ~5 500 – 7 000 tokens

max_tokens (output): 8 192
```

This means **a single Judge call can consume ~15 000 tokens** against the Vertex AI TPM (Tokens Per Minute) quota. On the default quota tier, two back-to-back audits within the same 60-second window will almost certainly trigger a 429.

### 3.3 Mitigation — Polite Delay + Exponential Backoff

Two complementary mechanisms are in place:

**A. Polite Sequential Delay (`jury_logic.js` — `runConflictSimulation`)**

Jury models are called **sequentially**, not concurrently, in the JS layer when operating in economy mode. A hard 10-second sleep is inserted between each juror call:

```js
// Polite delay: 10-second sleep between juror calls for quota refill
if (i < this.jurors.length - 1) {
    console.log('⏸️ Polite delay: Waiting 10 seconds for quota bucket refill...');
    await new Promise(resolve => setTimeout(resolve, 10000));
}
```

**B. Exponential Backoff (`jury_logic.js` — `exponentialBackoff`)**

On encountering a 429, up to 5 retry attempts are made with increasing delays:

```js
const delays = [1000, 3000, 10000]; // 1s, 3s, 10s
```

After delay exhaustion, EU failover activates for Claude. For Gemini/Llama, the error surfaces to the orchestrator and is logged.

**C. 429 = Proof of Access Convention**

In `pingJuror()`, a 429 response from a health-check prompt is **treated as a pass** (not a failure). A 429 confirms that our credentials are valid and the model is reachable — it only means the quota bucket is empty, not that the integration is broken.

```js
if (error.status === 429) {
    console.log(`⚠️ 429 quota limit for ${juror.name} - this indicates access is working`);
    return true; // 429 means we have access, just quota limited
}
```

### 3.4 Operational Guidance for Ivan

- **Do not run concurrent multi-document audits** during development without checking the current TPM quota in the Vertex AI console. The Judge alone can saturate the default `gemini-pro` TPM bucket.
- The `us-central1` failover for the Judge is **not automatic in current code** — it requires a manual endpoint swap in the orchestrator. Consider adding the `us-central1` path as the first retry target in the Judge's retry loop.
- Current 429 errors in the API metrics dashboard are **external quota limits**, not code failures. Connectivity and auth are verified as of March 2026.
- The Jury's Python orchestrator (`asyncio.gather`) and the JS layer (`Promise.all`) favour speed. If TPM quota is critically low, switch the Python caller to sequential invocation (mirroring the `runConflictSimulation` JS pattern) as a temporary throttle.

---

## Appendix: Key Files

| File | Role |
|---|---|
| `orchestrator.py` | Python backend — Jury orchestration, async calls, consensus generation |
| `jury_logic.js` | JS SDK layer — Anthropic/Google/Meta client management, retries, failover |
| `src/components/Dashboard.tsx` | React frontend — scan state machine, Supabase realtime listener |
| `src/lib/certificate.ts` | PDF certificate generation (jsPDF) |
| `supabase/migrations/` | All DDL including `audit_results` and triggers |
| `.env` | Runtime config — Vertex region, model IDs, credentials path. **Never commit.** |
| `AGENTS.md` | Agent security standards and project status baseline |
| `DECISIONS.log` | Permanent log of all architectural decisions |
