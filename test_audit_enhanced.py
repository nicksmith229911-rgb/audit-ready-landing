#!/usr/bin/env python3
"""
Test script for Triple AI Audit Orchestrator with Vertex AI
Run this after installing dependencies: pip install -r requirements.txt
"""

import asyncio
import json
import os
from dotenv import load_dotenv
from orchestrator import run_triple_audit, supabase

# Load environment variables with override
load_dotenv(override=True)

async def download_document_from_supabase():
    """Download document text from Supabase using service role key"""
    if not supabase:
        print("❌ Supabase client not initialized")
        return None
    
    try:
        print(f"🔍 [SUPABASE] Downloading most recent document...")
        
        # Get most recent scan record
        scan_result = supabase.table('scans').select('*').order('created_at', desc=True).limit(1).execute()
        
        if scan_result.data:
            scan_data = scan_result.data[0]
            scan_id = scan_data.get('id', 'Unknown')
            file_path = scan_data.get('storage_path') or scan_data.get('file_url', '')
            bucket_name = scan_data.get('storage_bucket', 'scans')
            
            print(f"📁 [SUPABASE] Scan ID: {scan_id}")
            print(f"📁 [SUPABASE] File path: {file_path}")
            print(f"📦 [SUPABASE] Bucket: {bucket_name}")
            
            # Download file from storage
            storage_result = supabase.storage.from_(bucket_name).download(file_path)
            
            if storage_result:
                # Convert to text (assuming PDF or text file)
                import base64
                file_content = storage_result
                
                # Simple text extraction for demo
                if hasattr(file_content, 'decode'):
                    document_text = file_content.decode('utf-8', errors='ignore')
                else:
                    # Handle binary data (would need OCR processing)
                    document_text = f"Document content from {file_path} (binary data - would need OCR)"
                
                print(f"✅ [SUPABASE] Document downloaded successfully ({len(document_text)} chars)")
                return document_text
            else:
                print(f"❌ [SUPABASE] Storage download failed: No data returned")
                return None
        else:
            print(f"❌ [SUPABASE] No scan records found")
            return None
            
    except Exception as e:
        print(f"❌ [SUPABASE] Download error: {str(e)}")
        return None

async def test_audit():
    """Test the triple audit with document from Supabase"""
    
    # Load environment variables
    load_dotenv()
    
    print("🚀 Starting Triple AI Audit Test with Vertex AI")
    print("=" * 60)
    
    # Verify environment variables for Vertex AI
    print("🔧 Vertex AI Environment Check:")
    print(f"  Anthropic Vertex API Key: {'✅ Set' if os.getenv('ANTHROPIC_VERTEX_API_KEY') else '❌ Missing'}")
    print(f"  Google Vertex AI Token: {'✅ Set' if os.getenv('GOOGLE_VERTEX_AI_TOKEN', os.getenv('GOOGLE_APPLICATION_CREDENTIALS')) else '❌ Missing'}")
    print(f"  Llama MaaS API Key: {'✅ Set' if os.getenv('LLAMA_MAAS_API_KEY') else '❌ Missing'}")
    print(f"  Google Credentials File: {'✅ Found' if os.path.exists('google-creds.json') else '❌ Missing'}")
    print(f"  Supabase URL: {'✅ Set' if os.getenv('SUPABASE_URL') else '❌ Missing'}")
    print(f"  Supabase Service Key: {'✅ Set' if os.getenv('SUPABASE_SERVICE_ROLE_KEY') else '❌ Missing'}")
    
    if supabase:
        print("  Supabase Client: ✅ Initialized")
    else:
        print("  Supabase Client: ❌ Not initialized")
    
    print("\n" + "-" * 40)
    print("🎯 VERTEX AI JURORS:")
    print("  Lead Juror: claude-sonnet-4-6 (Anthropic claude-3-5-sonnet@20240620)")
    print("  Technical Juror: gemini-1.5-pro (Vertex AI gemini-1.5-pro-002)")
    print("  Independent Juror: llama-4-maverick-17b-128e-instruct-maas")
    print("  Base URL: https://us-central1-aiplatform.googleapis.com/v1")
    print("  Using Service Account: google-creds.json")
    
    # Download document from Supabase
    document_text = await download_document_from_supabase()
    
    if not document_text:
        print("❌ Failed to download document from Supabase, using sample document...")
        # Fallback to sample document
        document_text = """
        EMPLOYEE HANDBOOK - COMPLIANCE SECTION
        
        1. DATA PRIVACY
        All employee data must be encrypted at rest and in transit.
        Personal information should only be accessed by authorized personnel.
        Customer data retention policies must comply with GDPR requirements.
        
        2. ACCESS CONTROL
        Multi-factor authentication is required for all systems.
        Access logs must be reviewed weekly by security team.
        Privileged accounts require quarterly access reviews.
        
        3. INCIDENT REPORTING
        All security incidents must be reported within 24 hours.
        Follow the incident response protocol documented in Appendix A.
        Critical incidents require immediate escalation to CISO.
        
        4. REGULATORY COMPLIANCE
        GDPR compliance for EU customer data is mandatory.
        CCPA requirements must be followed for California residents.
        Annual compliance audits are required by regulatory bodies.
        Financial records must be retained for 7 years per SOX requirements.
        
        5. SECURITY STANDARDS
        All servers must have latest security patches within 30 days.
        Network segmentation is required for production environments.
        Data loss prevention systems must monitor all egress traffic.
        """
    
    print(f"📄 Document ready for analysis ({len(document_text)} characters)")
    print("🤖 Sending to Vertex AI jurors for analysis...")
    
    try:
        # Run the audit
        result = await run_triple_audit(document_text)
        
        # Save results
        with open("audit_results.json", "w") as f:
            json.dump(result, f, indent=2)
        
        print("\n" + "=" * 60)
        print("✅ Triple Audit Complete - Results saved to audit_results.json")
        
        # Display key results
        consensus = result.get("consensus_report", {})
        print(f"\n📊 CONSENSUS SUMMARY:")
        print(f"  Risk Level: {consensus.get('risk_level', 'Unknown')}")
        print(f"  Agreement Score: {consensus.get('agreement_score', 0)}")
        print(f"  Consensus: {consensus.get('consensus_level', 'Unknown')}")
        if 'recommendation' in consensus:
            print(f"  Recommendation: {consensus['recommendation']}")
        else:
            print(f"  Recommendation: No recommendation available")
        
        # Show juror results
        print(f"\n🤖 VERTEX AI JUROR RESULTS:")
        for juror_result in result.get("individual_results", []):
            status = juror_result.get('status', 'Unknown')
            time = juror_result.get('response_time', 0)
            print(f"  {juror_result.get('juror', 'Unknown')}: {status} ({time:.2f}s)")
        
        # Show failed results
        failed_results = result.get("failed_results", [])
        if failed_results:
            print(f"\n❌ FAILED JURORS:")
            for failed in failed_results:
                print(f"  {failed.get('juror', 'Unknown')}: {failed.get('error', 'Unknown error')}")
        
        return result
        
    except Exception as e:
        print(f"❌ Audit failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return None

async def test_supabase_connection():
    """Test Supabase connection"""
    if not supabase:
        print("❌ Supabase client not initialized")
        return False
    
    try:
        # Test connection by querying scans table
        result = supabase.table('scans').select('count').execute()
        print(f"✅ Supabase connection successful - Found {len(result.data)} scan records")
        
        # Test audit_results table
        audit_result = supabase.table('audit_results').select('count').execute()
        print(f"✅ Audit results table accessible - Found {len(audit_result.data)} audit records")
        
        return True
    except Exception as e:
        print(f"❌ Supabase connection failed: {str(e)}")
        return False

async def main():
    """Main test function"""
    print("🔍 Running Vertex AI Triple Audit System Tests...")
    
    # Test Supabase connection
    await test_supabase_connection()
    
    print("\n" + "=" * 60)
    
    # Run audit test
    audit_result = await test_audit()
    
    if audit_result:
        print("\n🎉 ALL VERTEX AI TESTS COMPLETED SUCCESSFULLY!")
        print("📊 Check audit_results.json for detailed consensus analysis")
    else:
        print("\n❌ VERTEX AI AUDIT TEST FAILED!")

if __name__ == "__main__":
    asyncio.run(main())
