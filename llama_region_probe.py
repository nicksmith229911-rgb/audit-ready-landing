import os, asyncio, aiohttp, time
from dotenv import load_dotenv
from google.oauth2 import service_account
import google.auth.transport.requests

load_dotenv(override=True)
project = os.getenv('GOOGLE_PROJECT_ID')
creds = service_account.Credentials.from_service_account_file(
    os.getenv('GOOGLE_APPLICATION_CREDENTIALS', 'service-account.json'),
    scopes=['https://www.googleapis.com/auth/cloud-platform'])
req = google.auth.transport.requests.Request()
creds.refresh(req)

headers = {
    'Authorization': f'Bearer {creds.token}',
    'Content-Type': 'application/json',
    'x-goog-user-project': project
}

payload = {
    'model': 'meta/llama-4-maverick-17b-128e-instruct-maas',
    'messages': [{'role': 'user', 'content': 'OK'}],
    'stream': False, 'temperature': 0.1, 'max_tokens': 3
}

regions = [
    'us-east1', 'us-east4', 'us-east5',
    'us-central1', 'us-west1', 'us-west4',
    'northamerica-northeast1',
    'europe-west1', 'europe-west2', 'europe-west4',
    'europe-west6', 'europe-west9', 'europe-north1',
    'asia-east1', 'asia-northeast1', 'asia-northeast3',
    'asia-south1', 'asia-southeast1',
    'australia-southeast1',
    'me-central1', 'me-west1',
    'southamerica-east1',
]

async def check(session, region):
    url = f'https://{region}-aiplatform.googleapis.com/v1/projects/{project}/locations/{region}/endpoints/openapi/chat/completions'
    try:
        async with session.post(url, headers=headers, json=payload) as r:
            return region, r.status
    except asyncio.TimeoutError:
        return region, 'TIMEOUT'
    except Exception as e:
        return region, f'ERR'

async def main():
    print(f'=== LLAMA 4 MAVERICK — {len(regions)} regions (parallel, 10s timeout) ===')
    t0 = time.time()
    connector = aiohttp.TCPConnector(limit=22, force_close=True)
    timeout = aiohttp.ClientTimeout(connect=5, total=10)
    found = []
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        tasks = [check(session, r) for r in regions]
        results = await asyncio.gather(*tasks, return_exceptions=False)
    for region, status in sorted(results, key=lambda x: str(x[1])):
        if status == 200:
            print(f'  200 OK:  {region}')
            found.append(region)
        elif status == 429:
            print(f'  429 OK:  {region} (exists, quota hit)')
            found.append(region)
        elif status == 403:
            print(f'  403:     {region} (blocked)')
        elif status == 404:
            print(f'  404:     {region}')
        else:
            print(f'  {status}:  {region}')
    print(f'\nTotal time: {time.time()-t0:.1f}s')
    print(f'\n=== SUMMARY: Llama confirmed at {len(found)} regions ===')
    for r in found:
        print(f'  {r}')

asyncio.run(main())
