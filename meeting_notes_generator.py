import os
import re
import json
import warnings
import sys
import torch
import time
import traceback
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from loguru import logger
from omegaconf import OmegaConf
from dotenv import load_dotenv

# Internal imports
import config

# DRIVE SPACE & TEMP FIX: Redirect all large AI models and temp files
MODELS_DIR = os.getenv("MODELS_DIR", os.path.join(os.getcwd(), "models"))
os.makedirs(MODELS_DIR, exist_ok=True)

os.environ["HF_HOME"] = os.path.join(MODELS_DIR, "huggingface")
os.environ["NEMO_CACHE_DIR"] = os.path.join(MODELS_DIR, "nemo")
os.environ["TRANSFORMERS_CACHE"] = os.path.join(MODELS_DIR, "huggingface")

if os.name == 'nt':
    os.environ["TEMP"] = os.path.join(MODELS_DIR, "temp")
    os.environ["TMP"] = os.path.join(MODELS_DIR, "temp")
    os.makedirs(os.environ["TEMP"], exist_ok=True)

load_dotenv()

# AI & Transcription Engine Imports
import google.generativeai as genai
try:
    import nemo.collections.asr as nemo_asr
    NEMO_AVAILABLE = True
except Exception:
    NEMO_AVAILABLE = False

# PDF Imports
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

warnings.filterwarnings("ignore")

# -----------------------------
# CONFIG
# -----------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    logger.info("Gemini Engine Ready")
else:
    logger.error("GEMINI_API_KEY not found in environment")

OUTPUT_DIR = Path("meeting_outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

logger.remove()
logger.add(sys.stderr, format="<blue>{time:HH:mm:ss}</blue> | <level>{message}</level>")

def setup_fonts():
    base_path = Path(__file__).parent
    possible_paths = [
        base_path / "fonts" / "NotoSansDevanagari-Regular.ttf",
        Path("fonts/NotoSansDevanagari-Regular.ttf"),
    ]
    for font_path in possible_paths:
        if font_path.exists():
            try:
                pdfmetrics.registerFont(TTFont('HindiFont', str(font_path)))
                logger.info(f"Registered Hindi font: {font_path}")
                return True
            except Exception as e:
                logger.warning(f"Failed to register font {font_path}: {e}")
    return False

HINDI_AVAILABLE = setup_fonts()

# ==========================================================
# GEMINI-POWERED MEETING NOTES GENERATOR (v11.0)
# ==========================================================

class AdaptiveMeetingNotesGenerator:

    def __init__(self, audio_path=None):
        self.bot_name = config.get_setting("bot_name", "Renata AI | Meeting Assistant")
        logger.info(f"Initializing {self.bot_name} - Gemini 3.0 Flash Priority")
        
        self.audio_path = audio_path
        self.speaker_segments = []
        self.structured_transcript = []
        self.intel = {}
        self.analytics = {
            "speaker_time": {},
            "speaker_pc": {},
            "engagement_score": 0,
            "total_words": 0
        }
        self.gemini_file = None
        self.last_pdf_path = None
        self.last_json_path = None

    def _setup_diarizer_config(self, audio_path: str):
        out_dir = str(OUTPUT_DIR / "diarization")
        os.makedirs(out_dir, exist_ok=True)
        device = "cuda" if torch.cuda.is_available() else "cpu"

        config_dict = {
            "device": device,
            "num_workers": 0,
            "sample_rate": 16000,
            "verbose": True,
            "diarizer": {
                "manifest_filepath": "",
                "out_dir": out_dir,
                "oracle_vad": False,
                "batch_size": 1,
                "device": device,
                "verbose": True,
                "num_workers": 0,
                "pin_memory": False,
                "sample_rate": 16000,
                "speaker_embeddings": {
                    "model_path": "titanet_large",
                    "parameters": {
                        "window_length_in_sec": [1.5],
                        "shift_length_in_sec": [0.75],
                        "multiscale_weights": [1],
                        "save_embeddings": False
                    }
                },
                "clustering": {
                    "parameters": {
                        "oracle_num_speakers": False,
                        "max_num_speakers": 8,
                        "enhanced_mag_threshold": 1.0,
                        "sparse_search_volume": 30,
                        "max_rp_threshold": 0.25
                    }
                },
                "vad": {
                    "model_path": "vad_multilingual_marblenet",
                    "parameters": {
                        "window_length_in_sec": 0.15,
                        "shift_length_in_sec": 0.01,
                        "smoothing": "median",
                        "overlap": 0.5,
                        "onset": 0.1,
                        "offset": 0.1,
                        "pad_onset": 0.0,
                        "pad_offset": 0.0,
                        "min_duration_on": 0.1,
                        "min_duration_off": 0.1,
                        "filter_speech_low": 0.05
                    }
                }
            }
        }
        
        config_obj = OmegaConf.create(config_dict)
        OmegaConf.set_struct(config_obj, False)
        return config_obj
        
    def _generate_with_fallback(self, content, prompt_text=None):
        """Try Gemini 3.0 Flash and fallback to Gemini 2.5 Flash."""
        # Using model IDs that correspond to the requested versions
        models_to_try = ["gemini-3.0-flash", "gemini-2.5-flash"]
        
        # Mapping to actual available string IDs if the requested ones are symbolic
        actual_ids = {
            "gemini-3.0-flash": "gemini-3.0-flash", 
            "gemini-2.5-flash": "gemini-2.5-flash"
        }
        
        # Note: If these exact IDs give 404, we'll try the closest production equivalents 
        # but following user instruction to use these specific version strings.
        
        for model_id in models_to_try:
            try:
                id_to_use = actual_ids.get(model_id, model_id)
                logger.info(f"Attempting with model: {id_to_use}")
                model = genai.GenerativeModel(id_to_use)
                if prompt_text:
                    response = model.generate_content([content, prompt_text])
                else:
                    response = model.generate_content(content)
                return response
            except Exception as e:
                logger.warning(f"{model_id} failed: {e}")
                continue
        
        # Final emergency fallback if the exact version strings aren't yet in SDK but requested by name
        # We try 'gemini-2.0-flash' which is the current cutting-edge corresponding to the 'new' versions
        emergency_fallback = ["gemini-2.0-flash", "gemini-1.5-flash"]
        for model_id in emergency_fallback:
             try:
                logger.info(f"Emergency fallback attempt: {model_id}")
                model = genai.GenerativeModel(model_id)
                if prompt_text:
                    response = model.generate_content([content, prompt_text])
                else:
                    response = model.generate_content(content)
                return response
             except: continue

        raise Exception("All Gemini models failed.")

    def _upload_to_gemini(self, path):
        logger.info(f"Uploading {path} to Gemini...")
        try:
            file = genai.upload_file(path=path)
            while file.state.name == "PROCESSING":
                time.sleep(2)
                file = genai.get_file(file.name)
            if file.state.name == "FAILED":
                raise Exception("Gemini file upload failed")
            logger.info("Upload Complete")
            return file
        except Exception as e:
            logger.error(f"Gemini Upload Error: {e}")
            return None

    def perform_diarization(self, audio_path=None):
        """Run NeMo Speaker Diarization locally to assist Gemini."""
        path = audio_path or self.audio_path
        if not path or not os.path.exists(path):
            return

        if not NEMO_AVAILABLE:
            logger.error("NeMo not available for local diarization assist.")
            return

        try:
            logger.info("Running NVIDIA NeMo Speaker Diarization...")
            manifest_path = OUTPUT_DIR / "manifest.jsonl"
            with open(manifest_path, "w") as f:
                f.write(json.dumps({
                    "audio_filepath": os.path.abspath(path),
                    "offset": 0, "duration": None, "label": "infer", "text": "-"
                }) + "\n")

            diar_config = self._setup_diarizer_config(path)
            diar_config.diarizer.manifest_filepath = str(manifest_path)

            from nemo.collections.asr.models import ClusteringDiarizer
            diarizer = ClusteringDiarizer(cfg=diar_config)
            diarizer.diarize()

            rttm_files = list((OUTPUT_DIR / "diarization" / "pred_rttms").glob("*.rttm"))
            if rttm_files:
                self.speaker_segments = []
                with open(rttm_files[0], 'r') as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) >= 8:
                            start = float(parts[3])
                            dur = float(parts[4])
                            speaker = parts[7]
                            self.speaker_segments.append({'start': start, 'end': start + dur, 'speaker': speaker})
                logger.info(f"Local Diarization Finished: {len(self.speaker_segments)} segments.")
        except Exception as e:
            logger.error(f"NeMo local assist failed: {e}")

    def _align_with_diarization(self, gemini_segments):
        if not self.speaker_segments:
            return gemini_segments

        structured = []
        for g_seg in gemini_segments:
            timestamp = g_seg.get('timestamp', '00:00')
            try:
                if ':' in timestamp:
                    m, s = map(int, timestamp.split(':'))
                    t_sec = m * 60 + s
                else: t_sec = float(timestamp)
            except: t_sec = 0

            best_speaker = "Unknown"
            for d_seg in self.speaker_segments:
                if d_seg['start'] <= t_sec <= d_seg['end']:
                    best_speaker = d_seg['speaker']
                    break
            
            structured.append({"speaker": best_speaker, "text": g_seg['text'], "timestamp": timestamp})
        return structured

    def transcribe_audio(self, audio_path=None):
        path = audio_path or self.audio_path
        if not path or not os.path.exists(path): return

        try:
            if not self.gemini_file:
                self.gemini_file = self._upload_to_gemini(path)
            
            if not self.gemini_file: return

            prompt = """
            Transcribe the following audio file and identify different speakers (Speaker A, Speaker B, etc.). 
            Return the result ONLY as a JSON list of objects:
            [{"timestamp": "MM:SS", "speaker": "Speaker Name", "text": "..."}]
            """
            
            logger.info("Requesting Gemini Transcription & Diarization (3.0 Flash Priority)...")
            response = self._generate_with_fallback(self.gemini_file, prompt)
            
            raw_text = response.text.strip()
            json_match = re.search(r'\[.*\]', raw_text, re.DOTALL)
            if json_match:
                self.structured_transcript = json.loads(json_match.group())
                logger.info("Gemini Transcription & Diarization Complete.")
            else:
                logger.error("Failed to parse Gemini transcription JSON.")
        except Exception as e:
            logger.error(f"Gemini Transcription failed: {e}")

    def generate_summary(self):
        if not self.structured_transcript: return

        try:
            prompt = """
            Analyze the following meeting transcript and return a JSON object with:
            - summary_en: Professional executive summary in English.
            - summary_hi: Accurate Hindi version of the summary.
            - mom: List of key discussion points.
            - actions: List of objects with keys: "task", "owner", "deadline".
            Output ONLY valid JSON.
            """
            
            transcript_text = "\n".join([f"{s['speaker']} [{s['timestamp']}]: {s['text']}" for s in self.structured_transcript])
            full_prompt = f"{prompt}\n\nTranscript:\n{transcript_text}"
            
            logger.info("Generating Gemini AI Intelligence...")
            response = self._generate_with_fallback(full_prompt)
            raw = response.text.strip()
            
            json_match = re.search(r'\{.*\}', raw, re.DOTALL)
            if json_match:
                self.intel = json.loads(json_match.group())
                logger.info("Gemini Analysis Complete")
        except Exception as e:
            logger.error(f"Gemini Summary failed: {e}")

    def export_to_pdf(self):
        stem = Path(self.audio_path).stem if self.audio_path else "Meeting"
        filename = f"{stem}_Renata_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        pdf_path = OUTPUT_DIR / filename
        self.last_pdf_path = str(pdf_path)

        try:
            PAGE_W, PAGE_H = letter
            MARGIN = 0.75 * inch
            CONTENT_W = PAGE_W - 2 * MARGIN
            doc = SimpleDocTemplate(str(pdf_path), pagesize=letter, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=MARGIN)
            styles = getSampleStyleSheet()

            title_style = ParagraphStyle('RTitle', parent=styles['Heading1'], alignment=1, fontSize=18, spaceAfter=4)
            h2_style = ParagraphStyle('RH2', parent=styles['Heading2'], fontSize=13, spaceBefore=18, spaceAfter=6)
            normal_style = ParagraphStyle('RNormal', parent=styles['Normal'], fontSize=10, leading=14)
            hindi_style = ParagraphStyle('RHindi', parent=styles['Normal'], fontName='HindiFont' if HINDI_AVAILABLE else 'Helvetica', fontSize=11, leading=18)
            cell_style = ParagraphStyle('RCell', parent=styles['Normal'], fontSize=9, leading=12)

            elements = []
            elements.append(Paragraph(self.bot_name.upper(), title_style))
            elements.append(Paragraph(f"Intelligence Report • {datetime.now().strftime('%B %d, %Y')}", styles['Normal']))
            elements.append(Spacer(1, 12))

            if self.intel.get("summary_en"):
                elements.append(Paragraph("Executive Summary", h2_style))
                elements.append(Paragraph(self.intel["summary_en"], normal_style))

            if self.intel.get("summary_hi"):
                elements.append(Paragraph("Summary (Hindi)", h2_style))
                elements.append(Paragraph(self.intel["summary_hi"], hindi_style))

            if self.intel.get("mom"):
                elements.append(Paragraph("Minutes of Meeting", h2_style))
                for p in self.intel["mom"]: elements.append(Paragraph(f"• {p}", normal_style))

            actions = self.intel.get("actions", [])
            if actions:
                elements.append(Paragraph("Action Items", h2_style))
                action_data = [["Task", "Owner", "Deadline"]]
                for act in actions: action_data.append([act.get("task",""), act.get("owner",""), act.get("deadline","")])
                t = Table(action_data, colWidths=[CONTENT_W*0.6, CONTENT_W*0.2, CONTENT_W*0.2])
                t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.grey), ('TEXTCOLOR',(0,0),(-1,0),colors.whitesmoke), ('GRID',(0,0),(-1,-1),0.5,colors.grey)]))
                elements.append(t)

            if self.structured_transcript:
                elements.append(PageBreak())
                elements.append(Paragraph("Full Diarized Transcript", h2_style))
                trans_data = [["Time", "Speaker", "Text"]]
                for s in self.structured_transcript: trans_data.append([s.get('timestamp',''), s.get('speaker',''), s.get('text','')])
                t = Table(trans_data, colWidths=[CONTENT_W*0.1, CONTENT_W*0.2, CONTENT_W*0.7])
                t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.grey), ('GRID',(0,0),(-1,-1),0.3,colors.lightgrey)]))
                elements.append(t)

            doc.build(elements)
            logger.info(f"PDF Exported: {pdf_path}")
        except Exception as e:
            logger.error(f"PDF Export failed: {e}")

    def calculate_analytics(self):
        if not self.structured_transcript: return
        spks = {}
        total_words = 0
        for s in self.structured_transcript:
            spk = s['speaker']
            w = len(s['text'].split())
            total_words += w
            if spk not in spks: spks[spk] = {"words": 0}
            spks[spk]["words"] += w
        
        self.analytics = {"total_words": total_words, "num_speakers": len(spks), "engagement_score": min(100, (len(spks)*15) + (total_words/200))}
        self.intel["speaker_analytics"] = spks
        self.intel["engagement_metrics"] = self.analytics

    def process_meeting(self, audio_path: str):
        self.audio_path = audio_path
        self.transcribe_audio()
        self.calculate_analytics()
        self.generate_summary()
        self.export_to_pdf()
        
        # Save JSON
        data = {"intelligence": self.intel, "transcript": self.structured_transcript}
        json_path = OUTPUT_DIR / f"{Path(audio_path).stem}_data.json"
        with open(json_path, 'w') as f: json.dump(data, f, indent=4)
        self.last_json_path = str(json_path)
        logger.info("Gemini Hybrid Pipeline Finished.")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        generator = AdaptiveMeetingNotesGenerator(audio_path=sys.argv[1])
        generator.process_meeting(sys.argv[1])
    else:
        print("Usage: python meeting_notes_generator.py <audio_file.wav>")
