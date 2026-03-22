#!/usr/bin/env python3
"""
Triple AI Audit Orchestrator
Integrates Claude 4.6 Sonnet, Gemini 3.1 Flash, and Llama 4 Maverick for consensus auditing
"""

import json
import asyncio
import aiohttp
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
import os
from dotenv import load_dotenv
from supabase import create_client

# Google OAuth2 imports
try:
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account
    from google.auth import jwt
    GOOGLE_AUTH_AVAILABLE = True
except ImportError:
    GOOGLE_AUTH_AVAILABLE = False
    print("⚠️ Google auth library not available - will use fallback method")

# Load environment variables with override
load_dotenv(override=True)

def clean_env(key: str) -> str:
    """Aggressively clean environment variables"""
    return os.getenv(key, '').strip().replace('\n', '').replace('\r', '')

def get_oauth2_token(service_account_info: dict) -> Optional[str]:
    """Generate OAuth2 access token from service account credentials"""
    if not GOOGLE_AUTH_AVAILABLE:
        print("❌ Google auth library not available")
        return None
    
    try:
        # Create credentials object
        credentials = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=['https://www.googleapis.com/auth/cloud-platform']
        )
        
        # Refresh the credentials to get a fresh token
        request = Request()
        credentials.refresh(request)
        
        if credentials.token:
            print(f"✅ [OAUTH2] Token generated successfully")
            return credentials.token
        else:
            print(f"❌ [OAUTH2] No token generated")
            return None
            
    except Exception as e:
        print(f"❌ [OAUTH2] Token generation failed: {e}")
        return None

# Initialize Supabase client with Service Role Key (Master Key) for RLS bypass
supabase_url = clean_env('SUPABASE_URL')
supabase_service_key = clean_env('SUPABASE_SERVICE_ROLE_KEY')

if supabase_url and supabase_service_key:
    supabase = create_client(supabase_url, supabase_service_key)
    print(f"🔧 [SUPABASE] Client initialized with Service Role Key")
else:
    supabase = None
    print(f"❌ [SUPABASE] Missing credentials - client not initialized")

class AIJuror:
    """Base class for AI jurors with 2026 OAuth2 authentication"""
    
    def __init__(self, name: str, endpoint: str, headers: Dict[str, str]):
        self.name = name
        self.endpoint = endpoint
        self.response_time = 0
        self.success = False
        
        # 2026 OAuth2 Service Account Authentication with Auto-Refresh
        from google.oauth2 import service_account
        import google.auth.transport.requests

        self.creds = service_account.Credentials.from_service_account_file(
            os.getenv('GOOGLE_APPLICATION_CREDENTIALS', 'service-account.json'),
            scopes=['https://www.googleapis.com/auth/cloud-platform']
        )
        self.auth_request = google.auth.transport.requests.Request()

        def get_valid_headers():
            if not self.creds.valid:
                self.creds.refresh(self.auth_request)
            return {
                "Authorization": f"Bearer {self.creds.token}",
                "Content-Type": "application/json; charset=utf-8",
                # Required for Claude 4.6 on Vertex 2026
                "anthropic-version": "vertex-2023-10-16",
                "x-goog-user-project": os.getenv('GOOGLE_PROJECT_ID', '')
            }
        
        self.get_headers = get_valid_headers
    
    async def audit_document(self, document_text: str) -> Dict[str, Any]:
        """Send document to AI juror for analysis"""
        start_time = asyncio.get_event_loop().time()
        
        try:
            # Use auto-refresh headers for 2026 authentication
            headers = self.get_headers()
            
            async with aiohttp.ClientSession() as session:
                # Use different payload formats based on juror type
                if "claude" in self.name.lower():
                    # Anthropic-native payload for rawPredict endpoint
                    payload = {
                        "anthropic_version": "vertex-2023-10-16",
                        "messages": [
                            {"role": "user", "content": document_text}
                        ],
                        "max_tokens": 4096,
                        "temperature": 0.3,
                        "top_p": 0.9
                    }
                elif "llama" in self.name.lower():
                    # 2026 Fix: MaaS models require the OpenAI-style 'model' and 'messages' payload
                    payload = {
                        "model": "meta/llama-4-maverick-17b-128e-instruct-maas",
                        "messages": [{"role": "user", "content": document_text}],
                        "stream": False,
                        "temperature": 0.3,
                        "top_p": 0.9
                    }
                else:
                    # Vertex AI compliant payload for other models
                    prompt = f"""
You are a compliance auditor AI. Analyze the following document for compliance issues, risks, and violations.

DOCUMENT TO ANALYZE:
{document_text}

ANALYSIS REQUIREMENTS:
1. Identify compliance violations and risks
2. Assess risk level (Low, Medium, High)
3. Provide confidence score (0.0-1.0)
4. List specific issues found
5. Provide detailed analysis

RESPONSE FORMAT (JSON):
{{
  "risk_level": "Low|Medium|High",
  "confidence": 0.0-1.0,
  "issues": [
    {{
      "type": "issue_type",
      "severity": "Low|Medium|High", 
      "description": "detailed description"
    }}
  ],
  "analysis": "detailed compliance analysis"
}}

Timestamp: {datetime.now(timezone.utc).isoformat()}
"""

                    # Vertex AI compliant payload structure
                    payload = {
                        "contents": [{
                            "role": "user",
                            "parts": [{"text": prompt}]
                        }],
                        "generationConfig": {
                            "temperature": 0.3,
                            "topP": 0.9,
                            "responseMimeType": "application/json"
                        }
                    }
                
                async with session.post(self.endpoint, json=payload, headers=headers) as response:
                    self.response_time = asyncio.get_event_loop().time() - start_time
                    
                    if response.status == 200:
                        result = await response.json()
                        return self._parse_response(result)
                    else:
                        error_text = await response.text()
                        return {
                            "juror": self.name,
                            "status": "error",
                            "response_time": self.response_time,
                            "error": f"HTTP {response.status}: {error_text}"
                        }
                        
        except Exception as e:
            self.response_time = asyncio.get_event_loop().time() - start_time
            return {
                "juror": self.name,
                "status": "error",
                "response_time": self.response_time,
                "error": str(e)
            }
    
    def _parse_response(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Parse Vertex AI streaming response"""
        try:
            # Handle Vertex AI streaming response format
            if 'candidates' in result:
                candidate = result['candidates'][0]
                if 'content' in candidate:
                    content = candidate['content']
                    if 'parts' in content:
                        part = content['parts'][0]
                        if 'text' in part:
                            # Parse JSON response from text
                            response_text = part['text']
                            try:
                                analysis_result = json.loads(response_text)
                                return {
                                    "juror": self.name,
                                    "status": "success",
                                    "response_time": self.response_time,
                                    "analysis": analysis_result.get("analysis", ""),
                                    "confidence": float(analysis_result.get("confidence", 0.0)),
                                    "risk_level": analysis_result.get("risk_level", "Low"),
                                    "issues": analysis_result.get("issues", [])
                                }
                            except json.JSONDecodeError:
                                # Fallback if JSON parsing fails
                                return {
                                    "juror": self.name,
                                    "status": "success",
                                    "response_time": self.response_time,
                                    "analysis": response_text,
                                    "confidence": 0.5,
                                    "risk_level": "Medium",
                                    "issues": []
                                }
            
            # Fallback for unexpected response format
            return {
                "juror": self.name,
                "status": "success",
                "response_time": self.response_time,
                "analysis": str(result),
                "confidence": 0.5,
                "risk_level": "Medium",
                "issues": []
            }
            
        except Exception as e:
            return {
                "juror": self.name,
                "status": "error",
                "response_time": self.response_time,
                "error": f"Response parsing failed: {str(e)}"
            }

class TripleAuditOrchestrator:
    """Orchestrates triple AI audit for consensus"""
    
    def __init__(self):
        self.service_account_creds = None
        self.oauth2_token = None
        self.token_expiry = None
        self.jurors = self._initialize_jurors()
    
    def refresh_token_if_needed(self):
        """Refresh OAuth2 token if expired or missing"""
        import time
        current_time = time.time()
        
        # Refresh if token is missing or will expire within 5 minutes
        if (not self.oauth2_token or 
            not self.token_expiry or 
            current_time > (self.token_expiry - 300)):  # 5 minute buffer
            
            if self.service_account_creds:
                print(f"🔄 [OAUTH2] Refreshing token...")
                self.oauth2_token = get_oauth2_token(self.service_account_creds)
                if self.oauth2_token:
                    # Set expiry to 1 hour from now (typical OAuth2 token lifetime)
                    self.token_expiry = current_time + 3600
                    print(f"✅ [OAUTH2] Token refreshed successfully")
                else:
                    print(f"❌ [OAUTH2] Token refresh failed")
            else:
                print(f"❌ [OAUTH2] No service account available for refresh")
        
        return self.oauth2_token
    
    def _initialize_jurors(self) -> List[AIJuror]:
        """Initialize all three AI jurors using Vertex AI with Service Account"""
        jurors = []
        
        # Load Google service account credentials
        creds_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS', 'service-account.json')
        # Handle relative vs absolute paths
        if not os.path.isabs(creds_path):
            creds_path = os.path.join(os.path.dirname(__file__), creds_path)
            
        service_account_creds = None
        oauth2_token = None
        
        if os.path.exists(creds_path):
            try:
                with open(creds_path, 'r') as f:
                    service_account_creds = json.load(f)
                    sa_project_id = service_account_creds.get('project_id', '')
                    expected_project_id = os.getenv('GOOGLE_PROJECT_ID', '')
                    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = creds_path
                    print(f"🔧 [VERTEX] Service account loaded: {sa_project_id}")
                    
                    # Verify project ID matches ENV expectation
                    if expected_project_id and sa_project_id != expected_project_id:
                        print(f"❌ [VERTEX] Project ID mismatch. Expected: {expected_project_id}, Found in SA: {sa_project_id}")
                        # In strict environments, we might return []. Here we'll continue but warn.
                    else:
                        print(f"✅ [VERTEX] Project ID verified: {sa_project_id}")
                    
                    # Store credentials for refresh mechanism
                    self.service_account_creds = service_account_creds
                    
                    # Generate initial OAuth2 token
                    oauth2_token = get_oauth2_token(service_account_creds)
                    if not oauth2_token:
                        print(f"❌ [VERTEX] Failed to generate OAuth2 token")
                        return []
                    else:
                        # Store initial token and expiry
                        self.oauth2_token = oauth2_token
                        import time
                        self.token_expiry = time.time() + 3600  # 1 hour
                        
            except Exception as e:
                print(f"❌ [VERTEX] Failed to load service account: {e}")
                return []
        else:
            print(f"❌ [VERTEX] google-creds.json not found at {creds_path}")
            return []
        
        # Global variables for URIs
        active_project = os.getenv('GOOGLE_PROJECT_ID', service_account_creds.get('project_id', ''))
        
        # Lead Juror: Claude Sonnet 4.6 via AnthropicVertex (Global endpoint with EU failover)
        claude_headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {oauth2_token}",  # OAuth2 token
            "x-goog-user-project": active_project
        }
        jurors.append(AIJuror(
            "claude-opus-4-6",
            # 2026 Regional endpoint — Opus 4.6 confirmed 429 at europe-west4 (exists, quota limited)
            f"https://europe-west4-aiplatform.googleapis.com/v1/projects/{active_project}/locations/europe-west4/publishers/anthropic/models/claude-opus-4-6:rawPredict",
            claude_headers
        ))
        
        # Technical Juror: Gemini 2.5 Flash via Vertex AI (us-east5 region forced)
        gemini_headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {oauth2_token}",  # OAuth2 token
            "x-goog-user-project": active_project
        }
        jurors.append(AIJuror(
            "gemini-2.5-flash",
            f"https://us-east5-aiplatform.googleapis.com/v1/projects/{active_project}/locations/us-east5/publishers/google/models/gemini-2.5-flash:streamGenerateContent",
            gemini_headers
        ))
        
        # Independent Juror: Llama 3.1 405B via Meta Publisher (us-east1 region - working region)
        llama_headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {oauth2_token}",  # Use same OAuth2 token
            "x-goog-user-project": active_project
        }
        jurors.append(AIJuror(
            "llama-4-maverick",
            # 2026 GA MaaS Endpoint (OpenAPI Compatible) — us-east5 only (404 at us-east1)
            f"https://us-east5-aiplatform.googleapis.com/v1/projects/{active_project}/locations/us-east5/endpoints/openapi/chat/completions",
            llama_headers
        ))
        
        print(f"🤖 [JURORS] Initialized: {[juror.name for juror in jurors]}")
        return jurors
    
    async def run_triple_audit(self, document_text: str) -> Dict[str, Any]:
        """Run concurrent audit with all three jurors"""
        print(f"🚀 [ORCHESTRATOR] Starting triple audit for document ({len(document_text)} chars)")
        
        # Run all audits concurrently
        tasks = [juror.audit_document(document_text) for juror in self.jurors]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        successful_results = []
        failed_results = []
        
        for result in results:
            if isinstance(result, Exception):
                print(f"❌ [ORCHESTRATOR] Exception in audit: {result}")
                failed_results.append({"juror": "unknown", "error": str(result)})
            else:
                if result["status"] == "success":
                    successful_results.append(result)
                    print(f"✅ [ORCHESTRATOR] {result['juror']} completed in {result['response_time']:.2f}s")
                else:
                    failed_results.append(result)
                    print(f"❌ [ORCHESTRATOR] {result['juror']} failed: {result.get('error', 'Unknown error')}")
        
        # Generate consensus report
        consensus_report = self._generate_consensus_report(successful_results, failed_results)
        
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "document_length": len(document_text),
            "juror_count": len(self.jurors),
            "successful_audits": len(successful_results),
            "failed_audits": len(failed_results),
            "individual_results": successful_results,
            "failed_results": failed_results,
            "consensus_report": consensus_report
        }
    
    def _generate_consensus_report(self, successful_results: List[Dict[str, Any]], failed_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate consensus report from juror results"""
        if not successful_results:
            return {
                "status": "failed",
                "consensus_level": "No successful audits",
                "risk_level": "High",
                "message": "All AI jurors failed to analyze the document",
                "agreement_score": 0.0
            }
        
        # Analyze consensus
        total_jurors = len(successful_results)
        risk_levels = [result.get("risk_level", "Low") for result in successful_results]
        confidence_scores = [result.get("confidence", 0.0) for result in successful_results]
        
        # Calculate agreement
        high_risk_count = risk_levels.count("High")
        medium_risk_count = risk_levels.count("Medium")
        low_risk_count = risk_levels.count("Low")
        
        # Determine consensus risk level
        if high_risk_count >= 2:  # Majority high risk
            consensus_risk = "High"
            consensus_level = "Strong agreement on high risk"
        elif high_risk_count >= 1 and medium_risk_count >= 1:
            consensus_risk = "High"
            consensus_level = "Mixed agreement on elevated risk"
        elif medium_risk_count >= 2:
            consensus_risk = "Medium"
            consensus_level = "Strong agreement on medium risk"
        elif low_risk_count >= 2:
            consensus_risk = "Low"
            consensus_level = "Strong agreement on low risk"
        else:
            consensus_risk = "Medium"
            consensus_level = "No clear consensus"
        
        # Calculate agreement score
        most_common_risk = max(set(risk_levels), key=risk_levels.count)
        agreement_score = risk_levels.count(most_common_risk) / total_jurors
        
        # Compile common issues
        all_issues = []
        for result in successful_results:
            issues = result.get("issues", [])
            if isinstance(issues, list):
                all_issues.extend(issues)
        
        # Find most common issues
        issue_frequency = {}
        for issue in all_issues:
            issue_type = issue.get("type", "unknown")
            issue_frequency[issue_type] = issue_frequency.get(issue_type, 0) + 1
        
        common_issues = sorted(
            [{"type": k, "frequency": v} for k, v in issue_frequency.items()],
            key=lambda x: x["frequency"],
            reverse=True
        )[:5]  # Top 5 issues
        
        return {
            "status": "success",
            "consensus_level": consensus_level,
            "risk_level": consensus_risk,
            "agreement_score": round(agreement_score, 2),
            "risk_distribution": {
                "High": high_risk_count,
                "Medium": medium_risk_count,
                "Low": low_risk_count
            },
            "average_confidence": round(sum(confidence_scores) / len(confidence_scores), 2),
            "common_issues": common_issues,
            "recommendation": self._generate_recommendation(consensus_risk, common_issues)
        }
    
    def _generate_recommendation(self, risk_level: str, common_issues: List[Dict[str, Any]]) -> str:
        """Generate recommendation based on consensus risk level"""
        if risk_level == "High":
            return "IMMEDIATE ACTION REQUIRED: Multiple AI systems identified high-risk compliance issues. Review and address critical violations immediately."
        elif risk_level == "Medium":
            return "ATTENTION RECOMMENDED: Compliance issues detected that should be addressed within 30 days. Schedule review with compliance team."
        else:
            return "MONITORING ADVISED: Low-risk issues identified. Continue regular monitoring and address in next compliance cycle."

async def run_triple_audit(document_text: str) -> Dict[str, Any]:
    """Main function to run triple audit"""
    orchestrator = TripleAuditOrchestrator()
    result = await orchestrator.run_triple_audit(document_text)
    
    # Print consensus report summary
    consensus = result["consensus_report"]
    print(f"\n🎯 [CONSENSUS REPORT]")
    print(f"Status: {consensus['status']}")
    print(f"Risk Level: {consensus['risk_level']}")
    print(f"Agreement Score: {consensus['agreement_score']}")
    print(f"Consensus: {consensus['consensus_level']}")
    print(f"Recommendation: {consensus.get('recommendation', 'N/A')}")
    
    return result

if __name__ == "__main__":
    # Example usage
    sample_document = """
    Sample document text for testing...
    This would contain the actual document content to audit.
    """
    
    result = asyncio.run(run_triple_audit(sample_document))
    print(json.dumps(result, indent=2))
