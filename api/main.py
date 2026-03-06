import os
import sys
from pathlib import Path

# Get project root
api_dir = Path(__file__).resolve().parent
root_dir = api_dir.parent
sys.path.insert(0, str(root_dir))

# Import the actual app
try:
    print(">>> VERCEL ENTRY: IMPORTING MAIN APP...")
    from main import app as core_app
    print(">>> VERCEL ENTRY: IMPORT SUCCESS")
    handler = core_app
except Exception as e:
    import traceback
    error_msg = f"CRITICAL ENTRY ERROR: {e}\n{traceback.format_exc()}"
    print(error_msg)
    
    # Very basic fallback app to SHOW the user the error on the website
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    app = FastAPI()
    @app.get("/{rest_of_path:path}")
    async def caught_error(request: Request, rest_of_path: str):
        return JSONResponse(
            status_code=500,
            content={
                "error": "Vercel Entry Crash",
                "message": str(e),
                "traceback": traceback.format_exc()
            }
        )
    handler = app

# For Vercel FastAPI preset
app = handler
