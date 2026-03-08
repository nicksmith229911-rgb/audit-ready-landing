"""
Quick verification of Vertex AI setup with Google Service Account
"""

import os
import sys
import json
from dotenv import load_dotenv

# Fix Windows console encoding for emoji output
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# Load environment variables with override
load_dotenv(override=True)

def clean_env(key: str) -> str:
    """Aggressively clean environment variables"""
    return os.getenv(key, '').strip().replace('\n', '').replace('\r', '')

print("🚀 Vertex AI Triple Audit Setup Verification")
print("=" * 50)

# Check Google credentials
creds_path = os.path.join(os.path.dirname(__file__), 'google-creds.json')
project_id = None

if os.path.exists(creds_path):
    try:
        with open(creds_path, 'r') as f:
            creds = json.load(f)
            project_id = creds.get('project_id', 'Unknown')
            print(f"� Google Credentials File: ✅ Found")
            print(f"🔑 Project ID: {project_id}")
            
            # Verify correct project
            if project_id == 'audit-free-zone':
                print(f"✅ Project ID matches expected: audit-free-zone")
            else:
                print(f"❌ Project ID mismatch. Expected: audit-free-zone, Found: {project_id}")
    except Exception as e:
        print(f"❌ Error reading google-creds.json: {e}")
else:
    print(f"📁 Google Credentials File: ❌ Missing")

# Check Supabase
print(f"\n🗄️ Supabase:")
print(f"  SUPABASE_URL: {'✅ Set' if clean_env('SUPABASE_URL') else '❌ Missing'}")
print(f"  SUPABASE_SERVICE_ROLE_KEY: {'✅ Set' if clean_env('SUPABASE_SERVICE_ROLE_KEY') else '❌ Missing'}")

# Check Python modules
print(f"\n🐍 Python Modules:")
try:
    import aiohttp
    print("  aiohttp: ✅")
except ImportError:
    print("  aiohttp: ❌")

try:
    from supabase import create_client
    print("  supabase: ✅")
except ImportError:
    print("  supabase: ❌")

try:
    import asyncio
    print("  asyncio: ✅")
except ImportError:
    print("  asyncio: ❌")

if project_id:
    print(f"\n🎯 VERTEX AI JURORS CONFIGURED:")
    print("  Lead Juror: claude-sonnet-4-6 (Anthropic claude-3-5-sonnet@20240620)")
    print("  Technical Juror: gemini-1.5-pro (Vertex AI gemini-1.5-pro-002)")
    print("  Independent Juror: llama-4-maverick-17b-128e-instruct-maas")
    print(f"  All using Service Account: {creds_path}")
    print(f"  Base URL: https://us-central1-aiplatform.googleapis.com/v1")
else:
    print(f"\n❌ Cannot configure Vertex AI - missing or invalid google-creds.json")

print("\n✅ Setup verification complete!")
