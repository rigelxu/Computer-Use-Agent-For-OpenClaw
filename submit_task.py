import os, httpx
API_KEY = os.getenv("CUA_API_KEY", "dev-insecure-key")
resp = httpx.post('http://localhost:8100/task', json={
    'prompt': 'Rename the file on the desktop to xiaoxu.png. Use keyboard: first Ctrl+A to select all, then F2 to rename, type xiaoxu.png, press Enter.',
    'app_context': 'desktop'
}, headers={'Authorization': f'Bearer {API_KEY}'}, timeout=120)
print(resp.status_code, resp.text[:300])
