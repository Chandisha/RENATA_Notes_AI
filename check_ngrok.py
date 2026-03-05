import requests
import json
try:
    response = requests.get('http://localhost:4040/api/tunnels')
    print(json.dumps(response.json(), indent=2))
except Exception as e:
    print(f"No active Ngrok tunnels found.")
