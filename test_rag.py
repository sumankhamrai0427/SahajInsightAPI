import requests
import json

url = "http://localhost:3008/rag/chat"
payload = {
    "company_code": "sahaj",
    "session_id": "test",
    "user_query": "hello",
    "workspace_id": "1"
}
try:
    response = requests.post(url, json=payload)
    print("Status:", response.status_code)
    print("Response:", json.dumps(response.json(), indent=2))
except Exception as e:
    print("Error:", e)
