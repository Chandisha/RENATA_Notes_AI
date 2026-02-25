import os
import time
from fastapi import FastAPI, UploadFile, File
from faster_whisper import WhisperModel
import uvicorn
from pyngrok import ngrok
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# Load model once on GPU
DEVICE = "cuda" # This script is for the GPU machine
MODEL_SIZE = "large-v3"
print(f"Loading Faster-Whisper ({MODEL_SIZE}) on {DEVICE}...")
model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type="float16")

@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    # Save temp file
    temp_path = f"temp_{file.filename}"
    with open(temp_path, "wb") as f:
        f.write(await file.read())
    
    print(f"Transcribing: {file.filename}")
    segments, info = model.transcribe(temp_path, beam_size=5)
    
    results = []
    for s in segments:
        results.append({
            "start": s.start,
            "end": s.end,
            "text": s.text.strip()
        })
    
    os.remove(temp_path)
    return {"segments": results}

def start_server():
    # Start ngrok
    auth_token = os.getenv("NGROK_AUTH_TOKEN")
    if auth_token:
        ngrok.set_auth_token(auth_token)
    
    public_url = ngrok.connect(8000).public_url
    print("\n" + "="*60)
    print(f"GPU TRANSCRIPTION SERVER LIVE")
    print(f"URL: {public_url}")
    print(f"Add this to your laptop's .env: REMOTE_TRANSCRIPTION_URL={public_url}")
    print("="*60 + "\n")
    
    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    start_server()
