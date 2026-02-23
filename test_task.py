import os, requests

API_KEY = os.getenv("CUA_API_KEY", "dev-insecure-key")
resp = requests.post('http://localhost:8100/task',
    headers={'Authorization': f'Bearer {API_KEY}', 'Content-Type': 'application/json'},
    json={'prompt': '微信已经打开了。请用微信的搜索功能（Ctrl+F）搜索"不吃饭修仙"，点击搜索结果进入群聊，然后在输入框中输入"祝大家新年快乐，马年马上有钱—by 大徐的小徐"并按Enter发送。'})
print(resp.status_code)
print(resp.text)
