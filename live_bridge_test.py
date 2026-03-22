#!/usr/bin/env python3
"""
Live Bridge Test — Micro-Document Strategy
Proves the full Jury → Judge → Supabase pipeline works with live API calls.
~50-word document, ~500 total tokens, well under any TPM limit.
"""

import os
import asyncio
import time
from dotenv import load_dotenv
from supabase import create_client
from pipeline_bridge import run_full_pipeline

load_dotenv(override=True)

# --- Micro-Document (~50 words, ~75 tokens per model) ---
MICRO_DOCUMENT = """ACME Corp Compliance Policy v1.0:
All employee passwords must be minimum 12 characters with MFA enabled.
Customer PII must be encrypted using AES-256 at rest and in transit.
Security incidents must be reported to the CISO within 24 hours.
Annual compliance training is mandatory for all staff.
External USB devices are prohibited on corporate endpoints."""


async def run_test():
    """Run the live bridge test with micro-document."""
    print("=" * 60)
    print("🌉 LIVE BRIDGE TEST — Micro-Document Strategy")
    print("=" * 60)
    print(f"📋 Document: {len(MICRO_DOCUMENT.split())} words (~75 tokens/model)")
    print(f"📋 Pipeline: 3 Live Jurors → Judge → Supabase")
    print(f"📋 Delays: 10s between jurors, 15s before Judge")
    print(f"📋 Expected time: ~90-120s\n")

    test_start = time.time()

    # --- Supabase pre-flight ---
    sb_url = os.getenv("SUPABASE_URL")
    sb_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not sb_url or not sb_key:
        print("❌ FATAL: SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set")
        return False

    sb = create_client(sb_url, sb_key)

    # Verify tables exist
    try:
        sb.table("judge_reports").select("id").limit(1).execute()
        print("✅ Pre-flight: judge_reports table exists")
    except Exception as e:
        print(f"❌ FATAL: judge_reports table not found: {e}")
        return False

    # --- Create test scan row ---
    print("\n📝 Creating test scan row...")
    try:
        existing = sb.table("scans").select("user_id").limit(1).execute()
        test_user_id = existing.data[0]["user_id"] if existing.data else "00000000-0000-0000-0000-000000000000"

        test_scan = sb.table("scans").insert({
            "user_id": test_user_id,
            "file_name": "LIVE_BRIDGE_TEST.txt",
            "file_url": "test://live-bridge-test",
            "status": "pending"
        }).execute()

        test_scan_id = test_scan.data[0]["id"]
        print(f"✅ Test scan: {test_scan_id[:8]}...")
    except Exception as e:
        print(f"❌ FATAL: Could not create test scan: {e}")
        return False

    # --- Run the full pipeline ---
    print("\n" + "-" * 60)
    result = await run_full_pipeline(
        document_text=MICRO_DOCUMENT,
        scan_id=test_scan_id,
        user_id=test_user_id
    )
    print("-" * 60)

    # --- Verify ---
    if result["status"] == "success":
        print(f"\n🔍 Verifying Supabase write...")
        try:
            report = sb.table("judge_reports").select("*").eq("scan_id", test_scan_id).execute()
            if report.data:
                row = report.data[0]
                fields = ["executive_summary", "consensus_scorecard", "critical_risks_heatmap",
                           "areas_for_improvement", "maturity_rating", "appendices"]
                present = [f for f in fields if row.get(f) is not None]
                missing = [f for f in fields if row.get(f) is None]

                for f in present:
                    print(f"   ✅ {f}: populated")
                for f in missing:
                    print(f"   ❌ {f}: NULL")

                scan_check = sb.table("scans").select("status, compliance_score").eq("id", test_scan_id).execute()
                if scan_check.data:
                    print(f"\n   📊 scans.status = {scan_check.data[0].get('status')}")
                    print(f"   📊 scans.compliance_score = {scan_check.data[0].get('compliance_score')}")
            else:
                print("   ❌ No judge_reports row found")
                missing = ["all"]
        except Exception as e:
            print(f"   ❌ Verification failed: {e}")
            missing = ["verification_error"]
    else:
        missing = ["pipeline_failed"]

    # --- Final Report ---
    total_elapsed = time.time() - test_start
    print(f"\n{'=' * 60}")

    if result["status"] == "success" and not missing:
        print("🎉 LIVE BRIDGE TEST: PASSED")
    elif result["status"] == "success":
        print(f"⚠️  LIVE BRIDGE TEST: PARTIAL (missing: {missing})")
    elif result["status"] == "judge_failed":
        print("❌ LIVE BRIDGE TEST: JUDGE FAILED")
    else:
        print(f"❌ LIVE BRIDGE TEST: {result['status'].upper()}")

    print(f"{'=' * 60}")
    print(f"   Total time:       {total_elapsed:.1f}s")
    print(f"   Jury time:        {result.get('jury_time', 'N/A')}s")
    print(f"   Judge time:       {result.get('judge_time', 'N/A')}s")
    print(f"   Jurors succeeded:  {result.get('successful_jurors', 0)}/{result.get('total_jurors', 0)}")
    print(f"   Maturity rating:  {result.get('maturity_rating', 'N/A')}")
    print(f"   Test scan ID:     {test_scan_id[:8]}...")

    # Print individual juror scores
    if result.get("jury_results"):
        print(f"\n   📊 Juror Scores:")
        for jr in result["jury_results"]:
            status = "✅" if not jr.get("JUROR_FAILED") else "❌"
            print(f"      {status} {jr.get('juror', '?')}: {jr.get('compliance_score', '?')}/100")

    return result["status"] == "success" and not missing


if __name__ == "__main__":
    success = asyncio.run(run_test())
    exit(0 if success else 1)
