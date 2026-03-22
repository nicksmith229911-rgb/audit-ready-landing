# Vertex AI Quota Increase Request — Audit Ready Pipeline

**Project ID:** `audit-free-zone`
**Date:** 2026-03-18
**Purpose:** Production quota increase for a Triple-Engine Consensus AI compliance auditing pipeline (Jury + Judge architecture). The pipeline processes uploaded company policy documents (typical size: 30 pages / ~15,000 tokens) through three independent AI auditors and a final arbitrating Judge, then writes the result to Supabase.

---

## Pipeline Architecture Overview

```
User uploads Policy Document (PDF / up to 30 pages)
         ↓
   [JURY PHASE] — 3 independent AI auditors called sequentially
         ↓                    ↓                    ↓
 Juror 1: Claude     Juror 2: Gemini Flash    Juror 3: Llama
 (Lead Auditor)      (Technical Auditor)    (Independent Auditor)
         ↓                    ↓                    ↓
   3 JSON Audit Reports (risk level, issues, compliance analysis)
                         ↓
                  [JUDGE PHASE]
             Gemini 2.5 Pro — Evidence Arbitration
          Synthesizes 3 reports → 6-part final deliverable
                         ↓
              Supabase (judge_reports table)
```

Each audit is **user-triggered, one-shot, and sequential** — there are no loops, polling, or automated batch jobs. One document in, one report out. The pipeline enforces 10–15 second polite delays between model calls by design, making runaway quota consumption structurally impossible.

---

## Model, Region & Quota Requirements

| Model | Publisher | Region | TPM Request | RPM Request |
|---|---|---|---|---|
| `claude-opus-4-6` | Anthropic | `europe-west4` | **50,000** | **10** |
| `gemini-2.5-flash` | Google | `us-east5` | **100,000** | **15** |
| `llama-4-maverick-17b-128e-instruct-maas` | Meta (MaaS) | `us-east5` | **50,000** | **10** |
| `gemini-2.5-pro` | Google | `us-east5` | **100,000** | **5** |

**`claude-opus-4-6`** is the only model currently returning 429 errors in live testing and is the primary motivation for this request. All other models are confirmed working within current quota.

**`gemini-2.5-pro`** was substituted for `gemini-3.1-pro-preview` after a model availability scan confirmed the latter returns HTTP 404 across all regions in project `audit-free-zone`. `gemini-2.5-pro` returned HTTP 200 at `us-east5` and required only a single environment variable change.

**Regions** were selected based on live probe testing (HTTP status verification) across `us-east5`, `us-east1`, `us-central1`, and `europe-west4`. Only `europe-west4` hosts Claude; Gemini and Llama are both confirmed available exclusively at `us-east5`.

---

## Token Math — 30-Page Policy Document

| Stage | Tokens |
|---|---|
| Each Juror call (doc + prompt in, JSON report out) | ~18,500 |
| 3 Juror calls | ~55,500 |
| Judge call (3 reports + doc + system prompt in, 6-part report out) | ~25,000 |
| **Full pipeline per audit** | **~80,500 tokens** |

TPM figures are sized for **3–5 concurrent users** with 2× retry headroom. A single audit is a bounded, one-shot transaction with no feedback loops.
