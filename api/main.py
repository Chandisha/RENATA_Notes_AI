import os
import sys
from pathlib import Path

# Get project root
api_dir = Path(__file__).resolve().parent
root_dir = api_dir.parent
sys.path.insert(0, str(root_dir))

# Import the actual app
try:
    from main import app
except ImportError as e:
    print(f"FAILED TO IMPORT MAIN APP: {e}")
    # Very basic fallback for health checks
    from fastapi import FastAPI
    app = FastAPI()
    @app.get("/health")
    def health(): return {"status": "error", "message": str(e)}

# For Vercel FastAPI preset
handler = app
