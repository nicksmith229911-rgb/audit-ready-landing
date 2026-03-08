#!/usr/bin/env python3
"""
Test script for Triple AI Audit Orchestrator
"""

import asyncio
import json
from orchestrator import run_triple_audit

async def test_audit():
    """Test the triple audit with sample document"""
    
    # Sample document with various compliance scenarios
    sample_document = """
    EMPLOYEE HANDBOOK - COMPLIANCE SECTION
    
    1. DATA PRIVACY
    All employee data must be encrypted at rest and in transit.
    Personal information should only be accessed by authorized personnel.
    
    2. ACCESS CONTROL
    Multi-factor authentication is required for all systems.
    Access logs must be reviewed weekly by security team.
    
    3. INCIDENT REPORTING
    All security incidents must be reported within 24 hours.
    Follow the incident response protocol documented in Appendix A.
    
    4. REGULATORY COMPLIANCE
    GDPR compliance for EU customer data is mandatory.
    CCPA requirements must be followed for California residents.
    Annual compliance audits are required.
    """
    
    print("🚀 Starting Triple AI Audit Test")
    print("=" * 50)
    
    # Run the audit
    result = await run_triple_audit(sample_document)
    
    # Save results
    with open("audit_results.json", "w") as f:
        json.dump(result, f, indent=2)
    
    print("\n" + "=" * 50)
    print("✅ Triple Audit Complete - Results saved to audit_results.json")
    
    return result

if __name__ == "__main__":
    asyncio.run(test_audit())
