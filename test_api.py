import requests

payload = {
    "created_by": "user1",
    "session_id": "123",
    "workspace_id": 7
}
res = requests.post("http://127.0.0.1:3008/get_file_status", json=payload)
print(res.status_code)
print(res.text)
