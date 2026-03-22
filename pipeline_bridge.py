#!/usr/bin/env python3
"""
Pipeline Bridge — Wires the Jury (orchestrator.py) to the Judge (judge_engine.py)
Does NOT modify orchestrator.py. Imports TripleAuditOrchestrator and calls
jurors sequentially with polite delays for quota safety.
"""

import asyncio
import time
from typing import Dict, List, Any, Optional
from orchestrator import TripleAuditOrchestrator
from judge_engine import JudgeEngine

# Jury → Judge name mapping (orchestrator names → Constitution labels)
JUROR_NAME_MAP = {
    "claude-sonnet-4-6": "claude-opus-4-6",
    "gemini-2.5-flash": "gemini-3-flash",
    "llama-4-maverick": "llama-4-maverick",
}

# Polite delay constants (seconds)
INTER_JUROR_DELAY = 10   # Between each Jury call
PRE_JUDGE_DELAY = 15     # After Jury, before Judge


def translate_jury_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Translate a single Jury result to the format the Judge expects.
    Key change: confidence (0.0-1.0) → compliance_score (0-100)
    """
    translated = dict(result)

    # Map juror name to Constitution label
    juror_name = result.get("juror", "unknown")
    translated["juror"] = JUROR_NAME_MAP.get(juror_name, juror_name)

    # Derive compliance_score from confidence
    confidence = result.get("confidence", 0.0)
    try:
        translated["compliance_score"] = int(float(confidence) * 100)
    except (ValueError, TypeError):
        translated["compliance_score"] = 0

    # Mark failed jurors explicitly
    if result.get("status") != "success":
        translated["JUROR_FAILED"] = True
        translated["compliance_score"] = 0

    return translated


async def run_full_pipeline(
    document_text: str,
    scan_id: str,
    user_id: str,
    juror_delay: int = INTER_JUROR_DELAY,
    judge_delay: int = PRE_JUDGE_DELAY
) -> Dict[str, Any]:
    """
    Run the full Jury → Judge pipeline sequentially with polite delays.
    Returns the complete result dict including both Jury and Judge output.
    """
    pipeline_start = time.time()

    # --- Initialize ---
    print("🔧 Initializing pipeline...")
    orchestrator = TripleAuditOrchestrator()
    judge = JudgeEngine()

    if not orchestrator.jurors:
        print("❌ No jurors initialized — aborting pipeline")
        return {"status": "failed", "error": "No jurors initialized"}

    # --- Jury Phase: Sequential with polite delays ---
    print(f"\n🤖 JURY PHASE ({len(orchestrator.jurors)} jurors, sequential)")
    jury_results = []
    successful_count = 0

    for i, juror in enumerate(orchestrator.jurors):
        print(f"\n   [{i+1}/{len(orchestrator.jurors)}] Calling {juror.name}...")
        juror_start = time.time()

        try:
            result = await juror.audit_document(document_text)
            elapsed = time.time() - juror_start

            if result.get("status") == "success":
                successful_count += 1
                translated = translate_jury_result(result)
                jury_results.append(translated)
                print(f"   ✅ {juror.name}: score={translated['compliance_score']} in {elapsed:.1f}s")
            else:
                error = result.get("error", "Unknown error")
                # Create a failed entry so the Judge knows this juror existed
                failed_result = translate_jury_result(result)
                jury_results.append(failed_result)
                print(f"   ❌ {juror.name}: FAILED in {elapsed:.1f}s — {error[:100]}")

        except Exception as e:
            elapsed = time.time() - juror_start
            failed_result = {
                "juror": JUROR_NAME_MAP.get(juror.name, juror.name),
                "status": "error",
                "JUROR_FAILED": True,
                "compliance_score": 0,
                "response_time": elapsed,
                "error": str(e),
                "issues": [],
                "analysis": ""
            }
            jury_results.append(failed_result)
            print(f"   ❌ {juror.name}: EXCEPTION in {elapsed:.1f}s — {e}")

        # Polite delay between jurors (skip after last juror)
        if i < len(orchestrator.jurors) - 1:
            print(f"   ⏳ Polite delay: {juror_delay}s...")
            await asyncio.sleep(juror_delay)

    jury_elapsed = time.time() - pipeline_start

    # --- Check: minimum 1 successful juror required ---
    if successful_count == 0:
        print("\n❌ ALL JURORS FAILED — aborting pipeline (no data for Judge)")
        return {
            "status": "failed",
            "error": "All jurors failed",
            "jury_results": jury_results,
            "jury_time": jury_elapsed
        }

    print(f"\n📊 Jury complete: {successful_count}/{len(orchestrator.jurors)} succeeded in {jury_elapsed:.1f}s")

    # --- Pre-Judge delay ---
    print(f"⏳ Pre-Judge delay: {judge_delay}s (quota bucket refill)...")
    await asyncio.sleep(judge_delay)

    # --- Judge Phase ---
    print(f"\n⚖️  JUDGE PHASE")
    judge_start = time.time()
    judge_output = await judge.invoke_judge(jury_results, document_text)
    judge_elapsed = time.time() - judge_start

    if judge_output is None:
        print(f"\n❌ Judge failed after {judge_elapsed:.1f}s")
        return {
            "status": "judge_failed",
            "jury_results": jury_results,
            "jury_time": jury_elapsed,
            "judge_time": judge_elapsed
        }

    print(f"   ⏱️  Judge responded in {judge_elapsed:.1f}s")

    # --- Persist to Supabase ---
    print(f"\n💾 PERSISTENCE PHASE")
    persist_ok = judge.persist_to_supabase(scan_id, user_id, judge_output)

    total_elapsed = time.time() - pipeline_start

    return {
        "status": "success" if persist_ok else "persist_failed",
        "jury_results": jury_results,
        "judge_output": judge_output,
        "successful_jurors": successful_count,
        "total_jurors": len(orchestrator.jurors),
        "jury_time": round(jury_elapsed, 1),
        "judge_time": round(judge_elapsed, 1),
        "total_time": round(total_elapsed, 1),
        "maturity_rating": judge_output.get("maturity_rating", "N/A"),
        "persist_ok": persist_ok
    }
