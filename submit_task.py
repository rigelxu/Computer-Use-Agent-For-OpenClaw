import httpx
resp = httpx.post('http://localhost:8100/task', json={
    'prompt': 'Rename the file on the desktop to xiaoxu.png. Use keyboard: first Ctrl+A to select all, then F2 to rename, type xiaoxu.png, press Enter.',
    'app_context': 'desktop'
}, headers={'Authorization': 'Bearer test123'}, timeout=120)
print(resp.status_code, resp.text[:300])
