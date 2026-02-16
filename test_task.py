import requests

resp = requests.post('http://localhost:8100/task',
    headers={'Authorization': 'Bearer test123', 'Content-Type': 'application/json'},
    json={'prompt': '按下Win+S打开搜索，输入"微信"，打开微信应用。然后找到"不吃饭修仙"群聊，发送"@所有人 祝大家新年快乐，马年马上有钱[发]—by 大徐的小徐"'})
print(resp.status_code)
print(resp.text)
