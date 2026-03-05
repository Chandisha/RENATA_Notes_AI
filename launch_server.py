import subprocess
import os
import sys
import time
import requests
from loguru import logger

def check_ollama():
    logger.info("Checking Ollama status...")
    try:
        resp = requests.get("http://localhost:11434/api/tags")
        if resp.status_code == 200:
            logger.info("Ollama is RUNNING.")
            return True
    except:
        logger.warning("Ollama is NOT running or not reachable.")
        return False

def start_ollama():
    logger.info("Starting Ollama background process...")
    # On Windows, Ollama usually runs as a tray app, but we can try to launch it if not running
    try:
        subprocess.Popen(["ollama", "serve"], shell=True, creationflags=subprocess.CREATE_NEW_CONSOLE)
        time.sleep(5)
    except Exception as e:
        logger.error(f"Failed to start Ollama: {e}")

def start_fastapi():
    logger.info("Starting FastAPI Backend (main.py) on port 8000 with auto-reload...")
    subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"],
                     creationflags=subprocess.CREATE_NEW_CONSOLE)

def start_tunnel():
    logger.info("Starting Public Tunnel (Ngrok)...")
    # You can switch this to Cloudflare Tunnel if preferred
    try:
        from pyngrok import ngrok
        auth_token = os.getenv("NGROK_AUTH_TOKEN")
        if auth_token:
            ngrok.set_auth_token(auth_token)
        
        public_url = ngrok.connect(8000).public_url
        logger.success(f"PUBLIC BACKEND URL: {public_url}")
        logger.info("Update your Vercel Frontend's API_URL to this value.")
        
        # Save to a file for easy reference
        with open("backend_url.txt", "w") as f:
            f.write(public_url)
            
        return public_url
    except ImportError:
        logger.error("pyngrok not installed. Run: pip install pyngrok")
    except Exception as e:
        logger.error(f"Failed to start ngrok: {e}")

if __name__ == "__main__":
    logger.info("--- RENATA LOCAL SERVER INITIALIZER ---")
    
    if not check_ollama():
        start_ollama()
    
    start_fastapi()
    
    url = start_tunnel()
    
    logger.info("Backend is now LIVE and accessible from the web.")
    logger.info("Keep this window open to keep the server running.")
    
    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
