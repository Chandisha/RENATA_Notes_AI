import os
import sys
import torch
import subprocess
from loguru import logger

def check_dependencies():
    logger.info("Checking AI dependencies...")
    
    # 1. Faster-Whisper
    try:
        from faster_whisper import WhisperModel
        logger.info("Faster-Whisper: Installed")
    except ImportError:
        logger.error("Faster-Whisper: NOT INSTALLED. Run: pip install faster-whisper")
        
    # 2. Ollama
    try:
        import ollama
        logger.info("Ollama (Python Library): Installed")
    except ImportError:
        logger.error("Ollama (Library): NOT INSTALLED. Run: pip install ollama")
        
    # 3. NeMo
    try:
        import nemo.collections.asr as nemo_asr
        logger.info("NeMo Toolkit: Installed")
    except ImportError:
        logger.error("NeMo: NOT INSTALLED. Run: pip install nemo_toolkit[asr]")

def check_torch():
    logger.info("Checking Hardware Acceleration...")
    if torch.cuda.is_available():
        logger.info(f"GPU Mode: ON (Device: {torch.cuda.get_device_name(0)})")
    else:
        logger.warning("GPU Mode: OFF (CPU only). Processing will be slow.")

def test_ollama():
    host = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    logger.info(f"Testing Ollama connection to {host}...")
    try:
        import ollama
        client = ollama.Client(host=host)
        # Try a simple response
        resp = client.chat(model='gemma2', messages=[{'role': 'user', 'content': 'hi'}])
        logger.info(f"Ollama Response: {resp['message']['content'][:20]}...")
    except Exception as e:
        logger.error(f"Ollama Test Failed: {e}")
        logger.info("Tip: Ensure Ollama is running or exposed via ngrok if remote.")

if __name__ == "__main__":
    logger.info("--- RENA-MEET LOCAL AI DIAGNOSTIC ---")
    check_dependencies()
    check_torch()
    test_ollama()
