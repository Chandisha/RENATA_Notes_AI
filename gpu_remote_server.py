import os
import json
import torch
import shutil
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, BackgroundTasks
from faster_whisper import WhisperModel
import uvicorn
from pyngrok import ngrok
from dotenv import load_dotenv
from omegaconf import OmegaConf

load_dotenv()

app = FastAPI()

# --- GLOBALS ---
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Initializing Remote AI Server on {DEVICE}")

# Load Whisper
print("Loading Faster-Whisper...")
whisper_model = WhisperModel("large-v3", device=DEVICE, compute_type="float16")

# Setup for NeMo Diarization (Diarization needs temporary files)
TEMP_DIR = Path("remote_temp")
TEMP_DIR.mkdir(exist_ok=True)

def cleanup_temp(path: str):
    if os.path.exists(path):
        os.remove(path)
    shutil.rmtree(TEMP_DIR / Path(path).stem, ignore_errors=True)

@app.post("/process_audio")
async def process_audio(file: UploadFile = File(...)):
    """Handles BOTH Diarization and Transcription in one shot."""
    # 1. Save File
    file_id = f"{int(os.time.time())}_{file.filename}"
    temp_path = TEMP_DIR / file_id
    with open(temp_path, "wb") as f:
        f.write(await file.read())
    
    print(f"Received: {file.filename}. Starting Pipeline...")

    # 2. RUN TRANSCRIPTION
    print("Transcribing...")
    segments, _ = whisper_model.transcribe(str(temp_path), beam_size=5)
    whisper_results = [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segments]

    # 3. RUN DIARIZATION (NeMo)
    speaker_segments = []
    try:
        from nemo.collections.asr.models import ClusteringDiarizer
        
        # Setup NeMo Config
        out_dir = TEMP_DIR / Path(file_id).stem
        out_dir.mkdir(exist_ok=True)
        
        manifest_path = out_dir / "manifest.json"
        with open(manifest_path, "w") as f:
            f.write(json.dumps({"audio_filepath": str(temp_path.absolute()), "offset": 0, "duration": None, "label": "infer", "text": "-"}) + "\n")

        # Basic NeMo Config
        config = OmegaConf.create({
            "device": DEVICE,
            "diarizer": {
                "manifest_filepath": str(manifest_path),
                "out_dir": str(out_dir),
                "oracle_vad": False,
                "speaker_embeddings": {"model_path": "titanet_large"},
                "clustering": {"parameters": {"max_num_speakers": 8}},
                "vad": {"model_path": "vad_multilingual_marblenet"}
            }
        })
        
        print("Diarizing...")
        diarizer = ClusteringDiarizer(cfg=config)
        diarizer.diarize()

        # Parse RTTM
        rttm_files = list((out_dir / "pred_rttms").glob("*.rttm"))
        if rttm_files:
            with open(rttm_files[0], 'r') as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) >= 8:
                        start = float(parts[3])
                        dur = float(parts[4])
                        speaker_segments.append({'start': start, 'end': start + dur, 'speaker': parts[7]})
    except Exception as e:
        print(f"Diarization error: {e}")

    # Cleanup
    # BackgroundTasks could handle this, but for simplicity:
    # (Leaving it for now to avoid locking)

    return {
        "transcript": whisper_results,
        "speakers": speaker_segments
    }

def start():
    auth_token = os.getenv("NGROK_AUTH_TOKEN")
    if auth_token:
        ngrok.set_auth_token(auth_token)
    
    port = 8000
    public_url = ngrok.connect(port).public_url
    print("\n" + "="*70)
    print(f"RENA REMOTE GPU AI SERVER IS LIVE")
    print(f"URL: {public_url}")
    print(f"\nSET YOUR LAPTOP .env TO:")
    print(f"RENA_REMOTE_URL={public_url}")
    print("="*70 + "\n")
    
    uvicorn.run(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    import time # Needed for file_id
    start()
