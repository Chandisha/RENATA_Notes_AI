import sys
import os
from pyngrok import ngrok, conf
from dotenv import load_dotenv

load_dotenv()

# Use your token from .env
auth_token = os.getenv("NGROK_AUTH_TOKEN")
if auth_token and auth_token != "your_ngrok_token_here":
    ngrok.set_auth_token(auth_token)
    print("Using NGROK_AUTH_TOKEN from .env")
else:
    print("No ngrok token found in .env. Using free tier (may have limits).")

try:
    # Open a tunnel to port 11434 (Ollama)
    public_url = ngrok.connect(11434, "http")
    print("\n" + "="*50)
    print("NGROK TUNNEL STARTED")
    print(f"Ollama is now available at: {public_url}")
    print("="*50)
    print("\nCOPY the URL above and paste it into your .env file as OLLAMA_BASE_URL")
    print("\nPress Ctrl+C to stop it.")
    
    # Keep it running
    import time
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\nStopping ngrok...")
except Exception as e:
    print(f"Error: {e}")
    if "session closed" in str(e).lower():
        print("Tip: Try login to your ngrok account and get a fresh token.")
