#!/usr/bin/env python3
"""
E2E Judge Pipeline Test — Micro-Payload Strategy
Tests: Judge API connectivity → JSON schema enforcement → Supabase persistence
Uses hardcoded mock Jury data (zero Jury quota cost).
"""

import os
import asyncio
import json
import time
from dotenv import load_dotenv
from supabase import create_client
from judge_engine import JudgeEngine

load_dotenv(override=True)

# --- MOCK JURY REPORTS (Deliberate ≥15-point discrepancy: 40, 90, 85) ---
# These simulate a real scenario where Claude scored harshly and the other two disagreed.
MOCK_JURY_RESULTS = [
    {
        "juror": "claude-opus-4-6",
        "status": "success",
        "response_time": 3.2,
        "risk_level": "High",
        "confidence": 0.40,
        "compliance_score": 40,
        "issues": [
            {"type": "data_privacy", "severity": "High", "description": "No explicit GDPR DPO appointment documented"},
            {"type": "access_control", "severity": "High", "description": "MFA policy lacks enforcement mechanism"},
            {"type": "incident_response", "severity": "Medium", "description": "24-hour reporting window exceeds GDPR 72-hour but lacks escalation chain"}
        ],
        "analysis": "The policy contains significant compliance gaps. While data privacy principles are mentioned, the implementation details are insufficient for GDPR Article 37 compliance. Access control policies lack technical enforcement specifications."
    },
    {
        "juror": "gemini-3-flash",
        "status": "success",
        "response_time": 1.8,
        "risk_level": "Low",
        "confidence": 0.90,
        "compliance_score": 90,
        "issues": [
            {"type": "regulatory_compliance", "severity": "Low", "description": "Minor gap in CCPA opt-out mechanism documentation"}
        ],
        "analysis": "The policy demonstrates strong alignment with major compliance frameworks. Data encryption requirements are clearly stated, access controls are well-defined with MFA mandates, and incident reporting follows industry best practices."
    },
    {
        "juror": "llama-4-maverick",
        "status": "success",
        "response_time": 2.5,
        "risk_level": "Medium",
        "confidence": 0.85,
        "compliance_score": 85,
        "issues": [
            {"type": "data_privacy", "severity": "Medium", "description": "GDPR data retention policy unclear for cross-border transfers"},
            {"type": "security_standards", "severity": "Low", "description": "30-day patch window acceptable but could be tightened"}
        ],
        "analysis": "Overall compliance posture is solid with room for improvement. The policy covers essential areas but lacks specificity in cross-border data transfer mechanisms and could benefit from more granular patch management timelines."
    }
]

# --- MICRO DOCUMENT (2 sentences — minimal input tokens) ---
MOCK_ORIGINAL_DOCUMENT = """ACME Corp Employee Handbook - Compliance Section: All employee data must be encrypted at rest and in transit using AES-256. Multi-factor authentication is required for all production systems, and security incidents must be reported within 24 hours to the CISO."""


async def run_e2e_test():
    """Run the full Judge E2E pipeline test."""
    print("=" * 60)
    print("⚖️  E2E JUDGE PIPELINE TEST — Micro-Payload Strategy")
    print("=" * 60)
    print(f"📋 Strategy: Mock Jury (3 hardcoded reports) → Live Judge → Supabase")
    print(f"📋 Discrepancy: Claude=40, Gemini=90, Llama=85 (≥15-point gap)")
    print(f"📋 Quota cost: ONE Judge API call only (zero Jury tokens)\n")

    test_start = time.time()

    # --- Step 1: Initialize ---
    print("🔧 Step 1: Initializing Judge Engine...")
    try:
        judge = JudgeEngine()
    except Exception as e:
        print(f"❌ FATAL: Could not initialize JudgeEngine: {e}")
        return False

    # --- Step 2: Supabase pre-flight ---
    print("\n📋 Step 2: Supabase pre-flight check...")
    sb_url = os.getenv("SUPABASE_URL")
    sb_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not sb_url or not sb_key:
        print("❌ FATAL: SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set in .env")
        return False

    sb = create_client(sb_url, sb_key)

    # Check judge_reports table exists
    try:
        sb.table("judge_reports").select("id").limit(1).execute()
        print("✅ judge_reports table exists")
    except Exception as e:
        print(f"❌ FATAL: judge_reports table not found. Run the migration first!")
        print(f"   Error: {e}")
        print(f"   File: supabase/migrations/20240304_create_judge_reports.sql")
        return False

    # --- Step 3: Create test scan row ---
    print("\n📝 Step 3: Creating isolated test scan row...")
    try:
        # Get an existing user_id from the DB (needed for FK integrity)
        existing = sb.table("scans").select("user_id").limit(1).execute()
        if existing.data:
            test_user_id = existing.data[0]["user_id"]
        else:
            # If no scans exist, use a placeholder UUID
            test_user_id = "00000000-0000-0000-0000-000000000000"

        test_scan = sb.table("scans").insert({
            "user_id": test_user_id,
            "file_name": "E2E_JUDGE_TEST.txt",
            "file_url": "test://e2e-judge-pipeline-test",
            "status": "pending",
            "compliance_score": None
        }).execute()

        test_scan_id = test_scan.data[0]["id"]
        print(f"✅ Test scan created: {test_scan_id[:8]}...")
    except Exception as e:
        print(f"❌ FATAL: Could not create test scan: {e}")
        return False

    # --- Step 4: Call the Judge (LIVE API — the only real API call) ---
    print(f"\n⚖️  Step 4: Calling Judge ({judge.model_id})...")
    print(f"   Sending: 3 mock Jury reports + 2-sentence document")

    judge_start = time.time()
    judge_output = await judge.invoke_judge(MOCK_JURY_RESULTS, MOCK_ORIGINAL_DOCUMENT)
    judge_elapsed = time.time() - judge_start

    if judge_output is None:
        print(f"\n❌ Judge call failed after {judge_elapsed:.1f}s")
        print("   If 429: Judge model quota exhausted — retry in 60s")
        # Clean up the test scan
        sb.table("scans").delete().eq("id", test_scan_id).execute()
        print("🧹 Test scan cleaned up")
        return False

    print(f"   ⏱️  Judge responded in {judge_elapsed:.1f}s")

    # --- Step 5: Persist to Supabase ---
    print(f"\n💾 Step 5: Writing to Supabase...")
    persist_ok = judge.persist_to_supabase(test_scan_id, test_user_id, judge_output)

    if not persist_ok:
        print("❌ Supabase persistence failed")
        sb.table("scans").delete().eq("id", test_scan_id).execute()
        print("🧹 Test scan cleaned up")
        return False

    # --- Step 6: Verify the write ---
    print(f"\n🔍 Step 6: Verifying Supabase write...")
    try:
        verification = sb.table("judge_reports").select("*").eq("scan_id", test_scan_id).execute()

        if not verification.data:
            print("❌ VERIFICATION FAILED: No judge_reports row found for test scan")
            return False

        row = verification.data[0]
        required_fields = ["executive_summary", "consensus_scorecard", "critical_risks_heatmap",
                           "areas_for_improvement", "maturity_rating", "appendices"]

        present = []
        missing = []
        for field in required_fields:
            if row.get(field) is not None:
                present.append(field)
            else:
                missing.append(field)

        for field in present:
            print(f"   ✅ {field}: populated")
        for field in missing:
            print(f"   ❌ {field}: NULL")

        # Verify scans was updated
        scan_check = sb.table("scans").select("status, compliance_score").eq("id", test_scan_id).execute()
        if scan_check.data:
            scan_row = scan_check.data[0]
            print(f"\n   📊 scans.status = {scan_row.get('status')}")
            print(f"   📊 scans.compliance_score = {scan_row.get('compliance_score')}")

    except Exception as e:
        print(f"❌ Verification query failed: {e}")
        return False

    # --- Step 7: Final Report ---
    total_elapsed = time.time() - test_start
    print(f"\n{'=' * 60}")

    if not missing:
        print(f"🎉 E2E JUDGE PIPELINE TEST: PASSED")
    else:
        print(f"⚠️  E2E JUDGE PIPELINE TEST: PARTIAL (missing: {missing})")

    print(f"{'=' * 60}")
    print(f"   Total time:       {total_elapsed:.1f}s")
    print(f"   Judge API time:   {judge_elapsed:.1f}s")
    print(f"   Jury quota used:  0 tokens (mock data)")
    print(f"   Judge model:      {judge.model_id}")
    print(f"   Test scan ID:     {test_scan_id[:8]}...")
    print(f"   Maturity rating:  {judge_output.get('maturity_rating', 'N/A')}")
    print(f"\n💡 Verify in Supabase Dashboard:")
    print(f"   → Table Editor → judge_reports (check the new row)")
    print(f"   → Table Editor → scans (check status + compliance_score)")

    return len(missing) == 0


if __name__ == "__main__":
    success = asyncio.run(run_e2e_test())
    exit(0 if success else 1)
