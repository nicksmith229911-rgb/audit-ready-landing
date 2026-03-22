#!/usr/bin/env python3
"""
Cloud Run API Server — FastAPI HTTP layer for the Triple Audit Pipeline.

Receives PDF uploads, verifies the caller's Supabase session token locally
(HS256 JWT verification — no network call), extracts text via Document AI,
then runs the full Jury → Judge pipeline.

Entry point: uvicorn api_server:app --host 0.0.0.0 --port 8080
"""

import os
import time
import logging
from datetime import datetime, timezone
from collections import defaultdict
from typing import Dict, Any

from fastapi import FastAPI, HTTPException, Depends, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from jose import jwt, JWTError
from dotenv import load_dotenv

load_dotenv(override=True)

# --- Logging ---
logger = logging.getLogger("audit_ready.api")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s [%(name)s] %(message)s'
)

# --- App ---
app = FastAPI(
    title="Audit Ready Pipeline API",
    version="1.0.0",
    description="Triple-Engine Consensus Pipeline — JWT-authenticated API"
)

# --- CORS: restrict to your frontend domain ---
ALLOWED_ORIGINS = [
    os.getenv("FRONTEND_URL", "https://auditready.ai"),
    "http://localhost:3000",   # Sim site (local dev)
    "http://localhost:3001",   # Alt dev port
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["POST", "GET", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

# --- JWT Secret for local token verification ---
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")


# ============================================================
# AUTH: Local JWT verification (Option A — fast, no network)
# ============================================================

async def verify_user_token(request: Request) -> Dict[str, Any]:
    """
    Extract and verify the caller's Supabase session token locally.

    Uses the Supabase JWT Secret to verify the HS256 signature without
    making any network calls. Returns the decoded token payload if valid.

    The user_id (sub) from this verified token is used as the
    identity for all downstream operations — it cannot be forged.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or malformed Authorization header. Expected: Bearer <token>"
        )

    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Empty token")

    if not SUPABASE_JWT_SECRET:
        logger.error("SUPABASE_JWT_SECRET not configured in .env")
        raise HTTPException(status_code=500, detail="Server authentication not configured")

    try:
        # Decode and verify the JWT signature locally using the secret
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated"
        )

        user_id = payload.get("sub")
        email = payload.get("email", "unknown")

        if not user_id:
            raise HTTPException(status_code=401, detail="Token missing user ID (sub)")

        logger.info(f"Authenticated user: {user_id} ({email})")
        return {
            "id": user_id,
            "email": email,
            "role": payload.get("role", "authenticated"),
        }

    except JWTError as e:
        logger.warning(f"JWT verification failed: {e}")
        raise HTTPException(status_code=401, detail=f"Invalid or expired token: {str(e)}")


# ============================================================
# RATE LIMITING: In-memory per-user throttle
# ============================================================

_rate_store: Dict[str, list] = defaultdict(list)
MAX_AUDITS_PER_HOUR = 10


def check_rate_limit(user_id: str):
    """Enforce per-user rate limit. Raises 429 if exceeded."""
    now = time.time()
    # Clean entries older than 1 hour
    _rate_store[user_id] = [t for t in _rate_store[user_id] if now - t < 3600]
    if len(_rate_store[user_id]) >= MAX_AUDITS_PER_HOUR:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {MAX_AUDITS_PER_HOUR} audits per hour"
        )
    _rate_store[user_id].append(now)


# ============================================================
# SUPABASE CLIENT (lazy init)
# ============================================================

_supabase_client = None


def get_supabase():
    """Lazy-init Supabase client using service role key."""
    global _supabase_client
    if _supabase_client is None:
        from supabase import create_client
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        if not url or not key:
            raise HTTPException(500, "Supabase not configured")
        _supabase_client = create_client(url, key)
    return _supabase_client


# ============================================================
# ROUTES
# ============================================================

@app.get("/health")
async def health():
    """Health check — used by Cloud Run for readiness probes."""
    return {
        "status": "ok",
        "service": "audit-ready-pipeline",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@app.post("/api/v1/audit")
async def run_audit(
    file: UploadFile = File(...),
    user: dict = Depends(verify_user_token)
):
    """
    Run the full Triple-Engine Consensus pipeline.

    Flow:
        1. Verify user identity (JWT — local HS256 verification)
        2. Validate PDF upload (type, size, magic bytes)
        3. Extract text via Document AI
        4. Run Jury → Judge pipeline
        5. Persist results to Supabase
        6. Return structured result

    The user_id is extracted from the verified token — never from
    request parameters. This makes identity forgery impossible.
    """
    user_id = user["id"]  # From verified JWT — tamper-proof

    # --- Rate limit ---
    check_rate_limit(user_id)

    # --- Validate file type ---
    if file.content_type not in ("application/pdf", "application/x-pdf"):
        raise HTTPException(400, "Only PDF files are accepted")

    # --- Read file bytes ---
    pdf_bytes = await file.read()

    # --- Validate magic bytes (PDF starts with %PDF-) ---
    if not pdf_bytes[:5] == b"%PDF-":
        raise HTTPException(400, "File does not appear to be a valid PDF")

    # --- Validate file size (20MB max) ---
    max_size = 20 * 1024 * 1024
    if len(pdf_bytes) > max_size:
        raise HTTPException(400, f"File exceeds {max_size // (1024*1024)}MB limit")

    logger.info(f"Audit request: user={user_id}, file={file.filename}, size={len(pdf_bytes)} bytes")

    # --- Step 1: Create scan record in Supabase ---
    try:
        sb = get_supabase()
        scan = sb.table("scans").insert({
            "user_id": user_id,
            "status": "processing",
            "file_name": file.filename or "document.pdf",
        }).execute()
        scan_id = scan.data[0]["id"]
        logger.info(f"Created scan: {scan_id}")
    except Exception as e:
        logger.error(f"Failed to create scan record: {e}")
        raise HTTPException(500, f"Failed to create scan record: {str(e)}")

    # --- Step 2: Extract text via Document AI ---
    try:
        from extraction_service import ExtractionService
        extractor = ExtractionService()
        extraction_result = await extractor.extract_from_bytes(
            pdf_bytes=pdf_bytes,
            file_name=file.filename or "document.pdf"
        )

        if not extraction_result.success:
            sb.table("scans").update({"status": "extraction_failed"}).eq("id", scan_id).execute()
            raise HTTPException(422, f"Document AI extraction failed: {extraction_result.error}")

        document_text = extraction_result.text
        logger.info(
            f"Extraction complete: {extraction_result.page_count} pages, "
            f"{len(document_text)} chars, {extraction_result.processing_time:.1f}s"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Extraction error: {e}")
        sb.table("scans").update({"status": "extraction_failed"}).eq("id", scan_id).execute()
        raise HTTPException(500, f"Document extraction failed: {str(e)}")

    # --- Step 3: Run Jury → Judge pipeline ---
    try:
        from pipeline_bridge import run_full_pipeline
        result = await run_full_pipeline(
            document_text=document_text,
            scan_id=scan_id,
            user_id=user_id  # From verified JWT — cannot be forged
        )

        # Update scan status based on result
        final_status = "complete" if result.get("status") == "success" else "failed"
        sb.table("scans").update({"status": final_status}).eq("id", scan_id).execute()

        logger.info(
            f"Pipeline complete: status={result.get('status')}, "
            f"jurors={result.get('successful_jurors')}/{result.get('total_jurors')}, "
            f"total_time={result.get('total_time')}s"
        )

        return JSONResponse(content={
            "scan_id": scan_id,
            "status": result.get("status"),
            "successful_jurors": result.get("successful_jurors"),
            "total_jurors": result.get("total_jurors"),
            "maturity_rating": result.get("maturity_rating"),
            "jury_time": result.get("jury_time"),
            "judge_time": result.get("judge_time"),
            "total_time": result.get("total_time"),
            "persist_ok": result.get("persist_ok"),
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Pipeline error: {e}")
        sb.table("scans").update({"status": "pipeline_failed"}).eq("id", scan_id).execute()
        raise HTTPException(500, f"Pipeline execution failed: {str(e)}")


@app.delete("/api/v1/user/data")
async def delete_user_data(user: dict = Depends(verify_user_token)):
    """
    GDPR Art. 17 — Right to Erasure.
    Soft-deletes all data associated with the authenticated user.
    Hard deletion occurs after 30 days via scheduled cleanup.
    """
    user_id = user["id"]
    now = datetime.now(timezone.utc).isoformat()

    try:
        sb = get_supabase()
        sb.table("judge_reports").update({"deleted_at": now}).eq("user_id", user_id).execute()
        sb.table("scans").update({"deleted_at": now}).eq("user_id", user_id).execute()
        logger.info(f"User data soft-deleted: {user_id}")
        return {"status": "deletion_scheduled", "hard_delete_after": "30 days"}

    except Exception as e:
        logger.error(f"Data deletion failed: {e}")
        raise HTTPException(500, f"Data deletion failed: {str(e)}")


# ============================================================
# ENTRYPOINT
# ============================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
