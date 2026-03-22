#!/usr/bin/env python3
"""
Judge Engine — Gemini 3.1 Pro Consensus Arbiter
Always invoked after the Jury completes. The ≥15-point discrepancy rule
is handled cognitively by the Judge's Constitution prompt (Commandment #3),
NOT by Python routing logic.
"""

import os
import json
import asyncio
import aiohttp
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client
from google.oauth2 import service_account
import google.auth.transport.requests

load_dotenv(override=True)

# --- The Judge's Constitution (System Prompt) ---
# Derived from: archive/audit-ready-obsidian/11 Research & Frameworks/Judge constitution.md
# Scoring: Evidence-First + Median Guardrail hybrid (replaces rigid 45/30/25 weighted formula)
JUDGE_CONSTITUTION = """You are the Judge in a Triple-Engine Consensus compliance audit pipeline.
You receive three independent Jury reports (from Claude Opus 4.6, Llama 4 Maverick, and Gemini 3 Flash)
plus the Original Company Policy document. Your job is synthesis and arbitration, not raw analysis.

THE 10 COMMANDMENTS:

1. Use the Original Policy strictly for arbitration, not independent analysis.
   Your primary inputs are the three jury reports. Only consult the Original Policy to cross-check facts,
   resolve scoring disputes, or verify clause wording. Never add external knowledge.

2. Determine the Final Score via Evidence Arbitration.
   Do NOT use mathematical averages, fixed weights, or rigid formulas. Instead:
   A. Cross-examine the specific gaps and issues identified by the three jurors against the Original Policy.
      For each finding, verify it exists in the source text.
   B. Discard any finding that is hallucinated, factually incorrect, or unsupported by the text.
      A juror claiming a policy lacks a clause that is clearly present must have that finding thrown out.
   C. Build a Master Findings List of all verified, unique findings across all three jurors.
      De-duplicate overlapping issues. Every item on this list was confirmed against the source text.
   D. Synthesize the final compliance score from the Master Findings List.
      The score must reflect the severity and count of verified gaps — not any single juror's number.
   E. Median sanity check: if the synthesized score deviates by more than 15 points from the median
      of the three juror scores, explain the deviation explicitly in the appendices.
      The evidence-based score takes precedence, but large deviations demand justification.

3. Document all discarded testimony.
   In the appendices, list every finding that was discarded, which juror produced it,
   and why it was rejected (hallucination, misquote, unsupported by source text).
   Quote the conflicting claims and cite the Original Policy passage that disproves them.

4. Never invent new gaps or evidence. If all three reports are silent, say "No jury consensus".

5. Structure the final deliverable in this exact JSON schema (all fields required):
   - executive_summary: One-page plain-language verdict
   - consensus_scorecard: Framework scores including the evidence-based consensus score and median comparison
   - critical_risks_heatmap: Top 5 risks ranked by severity × likelihood
   - areas_for_improvement: Categorised as Quick Fixes / Medium-Term / Strategic Overhauls
   - maturity_rating: One of: Ad Hoc, Developing, Defined, Managed, Optimised
   - appendices: Master Findings List, Discarded Testimony Log, Jury Disagreements, Next 90-Day Action Plan

6. Use balanced, board-ready language. Never use "excellent" or "terrible".

7. Flag EU AI Act implications in the Critical Risks section.

8. Every recommendation must include: owner role, estimated effort, expected score uplift, dependencies.

9. Remain ruthlessly impartial. The verified evidence governs, not any single juror's bias.
   If a juror's overall score is accurate but supported by hallucinated findings, discard
   the findings but note the score alignment in the appendices.

10. End with a "Next 90-Day Action Plan" (5-7 bulleted items) inside the appendices.
"""


class JudgeEngine:
    """
    Orchestrates the Judge (Gemini 3.1 Pro) stage of the pipeline.
    Always invoked — no conditional gate. The 15-point rule is cognitive.
    """

    def __init__(self):
        self.project_id = os.getenv("GOOGLE_PROJECT_ID", "")
        self.region = os.getenv("JUDGE_REGION", "us-east5")
        self.model_id = os.getenv("JUDGE_MODEL_ID", "gemini-3.1-pro-preview")
        self.creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "service-account.json")

        # Supabase client (Service Role Key — bypasses RLS)
        sb_url = os.getenv("SUPABASE_URL", "")
        sb_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        self.supabase = create_client(sb_url, sb_key) if sb_url and sb_key else None

        # OAuth2 credentials (auto-refresh)
        if not os.path.isabs(self.creds_path):
            self.creds_path = os.path.join(os.path.dirname(__file__), self.creds_path)

        self.creds = service_account.Credentials.from_service_account_file(
            self.creds_path,
            scopes=['https://www.googleapis.com/auth/cloud-platform']
        )
        self.auth_request = google.auth.transport.requests.Request()

        # Backoff delays for 429 retries (longer than Jury — Judge is heavier)
        self.backoff_delays = [5, 15, 30]

        print(f"⚖️ [JUDGE] Engine initialized: {self.model_id} in {self.region}")

    def _get_headers(self) -> Dict[str, str]:
        """Get fresh OAuth2 headers, auto-refreshing if expired."""
        if not self.creds.valid:
            self.creds.refresh(self.auth_request)
        return {
            "Authorization": f"Bearer {self.creds.token}",
            "Content-Type": "application/json",
            "x-goog-user-project": self.project_id
        }

    def _build_endpoint(self) -> str:
        """Build the Vertex AI generateContent endpoint URL."""
        return (
            f"https://{self.region}-aiplatform.googleapis.com/v1/"
            f"projects/{self.project_id}/locations/{self.region}/"
            f"publishers/google/models/{self.model_id}:generateContent"
        )

    def _build_payload(self, jury_results: List[Dict[str, Any]], original_document: str) -> Dict[str, Any]:
        """
        Build the Judge's prompt payload with schema enforcement.
        Combines: Constitution + 3 Jury reports + original document.
        """
        # Format jury reports for insertion into the prompt
        jury_text_parts = []
        juror_labels = ["Juror A (Claude Opus 4.6)", "Juror B (Gemini 3 Flash)", "Juror C (Llama 4 Maverick)"]
        for i, result in enumerate(jury_results):
            label = juror_labels[i] if i < len(juror_labels) else f"Juror {i+1}"
            jury_text_parts.append(f"--- {label} Report ---\n{json.dumps(result, indent=2)}")

        jury_block = "\n\n".join(jury_text_parts)

        prompt_text = f"""{JUDGE_CONSTITUTION}

=== JURY REPORTS (Your Primary Inputs) ===

{jury_block}

=== ORIGINAL COMPANY POLICY (For Arbitration Only) ===

{original_document}

=== INSTRUCTIONS ===
Synthesize the above Jury reports into your 6-part deliverable.
Follow your Constitution strictly. Output valid JSON matching the required schema.
"""

        return {
            "contents": [{
                "role": "user",
                "parts": [{"text": prompt_text}]
            }],
            "generationConfig": {
                "temperature": 0.1,
                "topP": 0.85,
                "maxOutputTokens": 8192,
                "responseMimeType": "application/json"
            }
        }

    async def invoke_judge(self, jury_results: List[Dict[str, Any]], original_document: str) -> Optional[Dict[str, Any]]:
        """
        Call the Judge (Gemini 3.1 Pro) with all Jury reports + original document.
        Always called — no conditional gate. Retries with exponential backoff on 429.
        Returns parsed JSON dict on success, None on failure.
        """
        endpoint = self._build_endpoint()
        payload = self._build_payload(jury_results, original_document)

        print(f"⚖️ [JUDGE] Calling {self.model_id} at {self.region}...")

        for attempt in range(len(self.backoff_delays) + 1):
            try:
                headers = self._get_headers()

                async with aiohttp.ClientSession() as session:
                    async with session.post(endpoint, headers=headers, json=payload) as response:
                        if response.status == 200:
                            data = await response.json()
                            raw_text = data['candidates'][0]['content']['parts'][0]['text']

                            # Parse — may already be dict if Vertex returns native JSON
                            if isinstance(raw_text, str):
                                judge_output = json.loads(raw_text)
                            else:
                                judge_output = raw_text

                            # Validate all 6 fields present
                            required = ["executive_summary", "consensus_scorecard", "critical_risks_heatmap",
                                        "areas_for_improvement", "maturity_rating", "appendices"]
                            missing = [f for f in required if not judge_output.get(f)]
                            if missing:
                                print(f"❌ [JUDGE] Response missing required fields: {missing}")
                                return None

                            print("✅ [JUDGE] Responded with valid 6-part JSON!")
                            return judge_output

                        elif response.status == 429:
                            if attempt < len(self.backoff_delays):
                                delay = self.backoff_delays[attempt]
                                print(f"⚠️ [JUDGE] 429 Quota Exhausted — backing off {delay}s (attempt {attempt + 1}/{len(self.backoff_delays)})")
                                await asyncio.sleep(delay)
                            else:
                                print("❌ [JUDGE] 429 Quota Exhausted — all retries failed. Retry in 60s.")
                                return None
                        else:
                            error_text = await response.text()
                            print(f"❌ [JUDGE] HTTP {response.status}: {error_text[:300]}")
                            return None

            except Exception as e:
                print(f"❌ [JUDGE] Exception on attempt {attempt + 1}: {e}")
                if attempt < len(self.backoff_delays):
                    delay = self.backoff_delays[attempt]
                    print(f"⏳ [JUDGE] Retrying in {delay}s...")
                    await asyncio.sleep(delay)
                else:
                    return None

        return None

    def persist_to_supabase(self, scan_id: str, user_id: str, judge_output: Dict[str, Any]) -> bool:
        """
        Write the Judge's 6-part deliverable to judge_reports and
        update scans.compliance_score with the authoritative score.
        """
        if not self.supabase:
            print("❌ [JUDGE] Supabase client not initialized")
            return False

        try:
            # 1. Insert into judge_reports
            insert_payload = {
                "scan_id": scan_id,
                "user_id": user_id,
                "executive_summary": judge_output.get("executive_summary"),
                "consensus_scorecard": judge_output.get("consensus_scorecard"),
                "critical_risks_heatmap": judge_output.get("critical_risks_heatmap"),
                "areas_for_improvement": judge_output.get("areas_for_improvement"),
                "maturity_rating": judge_output.get("maturity_rating"),
                "appendices": judge_output.get("appendices"),
            }

            self.supabase.table("judge_reports").insert(insert_payload).execute()
            print("✅ [JUDGE] Written to judge_reports table")

            # 2. Extract authoritative score from consensus_scorecard and update scans
            scorecard = judge_output.get("consensus_scorecard", {})
            auth_score = None

            # Handle scorecard being a dict or a list
            if isinstance(scorecard, dict):
                auth_score = (
                    scorecard.get("overall_score")
                    or scorecard.get("overall_compliance_score")
                    or scorecard.get("weighted_average")
                    or scorecard.get("overall_weighted_score")
                )
            elif isinstance(scorecard, list):
                # Look for an overall/weighted entry in the array
                for entry in scorecard:
                    if isinstance(entry, dict):
                        name = str(entry.get("framework", entry.get("name", ""))).lower()
                        if "overall" in name or "weighted" in name or "consensus" in name:
                            auth_score = entry.get("score") or entry.get("weighted_score")
                            break
                # Fallback: average all numeric scores in the array
                if auth_score is None and scorecard:
                    scores = []
                    for entry in scorecard:
                        if isinstance(entry, dict):
                            s = entry.get("weighted_consensus_score") or entry.get("score") or entry.get("weighted_score")
                            if s is not None:
                                try:
                                    scores.append(float(s))
                                except (ValueError, TypeError):
                                    pass
                    if scores:
                        auth_score = sum(scores) / len(scores)

            update_data = {"status": "completed"}
            if auth_score is not None:
                try:
                    update_data["compliance_score"] = int(float(auth_score))
                except (ValueError, TypeError):
                    pass

            self.supabase.table("scans").update(update_data).eq("id", scan_id).execute()
            print(f"✅ [JUDGE] scans row updated: {update_data}")

            return True

        except Exception as e:
            print(f"❌ [JUDGE] Supabase persistence failed: {e}")
            return False
