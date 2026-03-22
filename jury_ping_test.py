import os
import asyncio
import aiohttp
from dotenv import load_dotenv
from supabase import create_client
from google.oauth2 import service_account
import google.auth.transport.requests

load_dotenv(override=True)

def ping_supabase():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    try:
        sb = create_client(url, key)
        res = sb.table("scans").select("*", count="exact").limit(1).execute()
        print("Database Ping (Supabase): ONLINE")
    except Exception as e:
        err_str = str(e)
        if "403" in err_str or "Permission" in err_str:
            print("Database Ping (Supabase): PERMISSION DENIED (403)")
        elif "429" in err_str:
            print("Database Ping (Supabase): AUTH SUCCESS / QUOTA EXHAUSTED")
        else:
            print(f"Database Ping (Supabase): ERROR ({e})")

async def ping_model(session, name, base_urls, headers, payload):
    best_status = 404
    best_message = ""
    for url in base_urls:
        try:
            async with session.post(url, headers=headers, json=payload) as response:
                status = response.status
                text = await response.text()
                
                # We prioritize the requested exit states
                if status == 200:
                    print(f"{name}: ONLINE")
                    return
                elif status == 429:
                    best_status = 429
                    best_message = f"{name}: AUTH SUCCESS / QUOTA EXHAUSTED"
                    break
                elif status == 403:
                    if best_status not in [429]:
                        best_status = 403
                        best_message = f"{name}: PERMISSION DENIED (403)"
                elif status != 404:
                    if best_status not in [429, 403]:
                        best_status = status
                        best_message = f"{name}: HTTP {status} - {text[:100]}"
        except Exception as e:
            pass
            
    if best_status == 404:
        print(f"{name}: HTTP 404 NOT FOUND (Check Model ID or Region)")
    else:
        print(best_message)

async def main():
    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "service-account.json")
    project_id = os.getenv("GOOGLE_PROJECT_ID")
    
    print(f"Initializing Vertex AI environment for Project: {project_id}")
    
    creds = service_account.Credentials.from_service_account_file(
        creds_path,
        scopes=['https://www.googleapis.com/auth/cloud-platform']
    )
    request = google.auth.transport.requests.Request()
    creds.refresh(request)
    token = creds.token
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "x-goog-user-project": project_id
    }
    
    gemini_id = os.getenv("GEMINI_MODEL_ID", "gemini-3-flash-preview")
    claude_id = os.getenv("CLAUDE_MODEL_ID", "claude-opus-4-6@default")
    llama_id = os.getenv("LLAMA_MODEL_ID", "llama-4-maverick-17b-128e-instruct-maas")
    
    regions = ["us-central1", "us-east5", "us-east1", "europe-west4"]
    versions = ["v1", "v1beta1"]
    
    gemini_urls = [
        f"https://{host}/{v}/projects/{project_id}/locations/global/publishers/google/models/{gemini_id}:{method}"
        for host in ["aiplatform.googleapis.com", "global-aiplatform.googleapis.com"]
        for v in versions for method in ["generateContent", "streamGenerateContent"]
    ]
    claude_urls = [f"https://{r}-aiplatform.googleapis.com/{v}/projects/{project_id}/locations/{r}/publishers/anthropic/models/{claude_id}:rawPredict" 
                   for r in regions for v in versions]
    llama_urls = [f"https://{r}-aiplatform.googleapis.com/{v}/projects/{project_id}/locations/{r}/endpoints/openapi/chat/completions" 
                  for r in regions for v in versions]
    
    models = [
        {
            "id": gemini_id,
            "urls": gemini_urls,
            "payload": {
                "contents": [{"role": "user", "parts": [{"text": "System Check: Respond with 'ACK'"}]}]
            }
        },
        {
            "id": claude_id,
            "urls": claude_urls,
            "payload": {
                "anthropic_version": "vertex-2023-10-16",
                "messages": [{"role": "user", "content": "System Check: Respond with 'ACK'"}],
                "max_tokens": 10
            }
        },
        {
            "id": llama_id,
            "urls": llama_urls,
            "payload": {
                "model": f"meta/{llama_id}",
                "messages": [{"role": "user", "content": "System Check: Respond with 'ACK'"}]
            }
        }
    ]
    
    print("\n--- The Database Ping ---")
    ping_supabase()
    
    print("\n--- The AI Pings ---")
    async with aiohttp.ClientSession() as session:
        tasks = []
        for m in models:
            tasks.append(ping_model(session, m["id"], m["urls"], headers, m["payload"]))
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
