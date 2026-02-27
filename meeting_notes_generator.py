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

# DRIVE SPACE & TEMP FIX: Redirect all large AI models and temp files to D: drive
os.environ["HF_HOME"] = "D:\\RENATA_Models\\huggingface"
os.environ["NEMO_CACHE_DIR"] = "D:\\RENATA_Models\\nemo"
os.environ["TRANSFORMERS_CACHE"] = "D:\\RENATA_Models\\huggingface"
os.environ["TEMP"] = "D:\\RENATA_Models\\temp"
os.environ["TMP"] = "D:\\RENATA_Models\\temp"
os.makedirs("D:\\RENATA_Models\\temp", exist_ok=True)
os.makedirs("D:\\RENATA_Models", exist_ok=True)

load_dotenv()

# AI & Transcription Engine Imports
import google.generativeai as genai
try:
    import nemo.collections.asr as nemo_asr
    NEMO_AVAILABLE = True
except Exception:
    NEMO_AVAILABLE = False

try:
    import ollama
    OLLAMA_AVAILABLE = True
except:
    OLLAMA_AVAILABLE = False

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
    logger.info("Gemini 3 Flash Ready")
else:
    logger.error("GEMINI_API_KEY not found in environment")

OUTPUT_DIR = Path("meeting_outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

logger.remove()
logger.add(sys.stderr, format="<blue>{time:HH:mm:ss}</blue> | <level>{message}</level>")

def setup_fonts():
    # Try local fonts directory
    possible_paths = [
        Path("fonts/NotoSansDevanagari-Regular.ttf"),
        Path(r"C:\Users\admin\Desktop\RENA-Meet\fonts\NotoSansDevanagari-Regular.ttf"),
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
# ADAPTIVE MEETING NOTES GENERATOR (v9.5 Hybrid)
# ==========================================================

class AdaptiveMeetingNotesGenerator:

    def __init__(self, audio_path=None):
        self.bot_name = config.get_setting("bot_name", "Renata AI | Meeting Assistant")
        logger.info(f"Initializing {self.bot_name} - Gemini 3 Flash Engine")
        
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

    def _setup_diarizer_config(self, audio_path: str):
        out_dir = str(OUTPUT_DIR / "diarization")
        os.makedirs(out_dir, exist_ok=True)

        device = "cuda" if torch.cuda.is_available() else "cpu"

        # Build a plain dictionary first to avoid OmegaConf struct issues initially
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
                        "window_length_in_sec": [1.5], # Simplified for CPU speed
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
        OmegaConf.set_struct(config_obj.diarizer, False)
        return config_obj
        
    def _generate_with_fallback(self, content, prompt_text=None):
        """Try Gemini 3 Flash and Gemini 2.5 Flash as per technical IDs."""
        models_to_try = ["gemini-3-flash-preview", "gemini-2.5-flash"]
        
        for model_id in models_to_try:
            try:
                logger.info(f"Attempting with model: {model_id}")
                model = genai.GenerativeModel(model_id)
                if prompt_text:
                    response = model.generate_content([content, prompt_text])
                else:
                    response = model.generate_content(content)
                return response
            except Exception as e:
                logger.warning(f"{model_id} failed: {e}")
                continue
        
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
        """Run NeMo Speaker Diarization."""
        path = audio_path or self.audio_path
        if not path or not os.path.exists(path):
            logger.error("Diarization failed: No audio path provided.")
            return

        if not NEMO_AVAILABLE:
            logger.error("NeMo not installed. Cannot perform local diarization.")
            return

        try:
            logger.info("Running NVIDIA NeMo Speaker Diarization...")
            device = "cuda" if torch.cuda.is_available() else "cpu"
            
            manifest_path = OUTPUT_DIR / "manifest.jsonl"
            with open(manifest_path, "w") as f:
                f.write(json.dumps({
                    "audio_filepath": os.path.abspath(path),
                    "offset": 0,
                    "duration": None,
                    "label": "infer",
                    "text": "-"
                }) + "\n")

            diar_config = self._setup_diarizer_config(path)
            diar_config.diarizer.manifest_filepath = str(manifest_path)

            from nemo.collections.asr.models import ClusteringDiarizer
            diarizer = ClusteringDiarizer(cfg=diar_config)
            diarizer.diarize()

            # Parse RTTM
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
                logger.info(f"Found {len(self.speaker_segments)} speech segments via NeMo.")
        except Exception as e:
            logger.error(f"NeMo Diarization failed: {e}")
            logger.debug(traceback.format_exc())

    def _align_with_diarization(self, gemini_segments):
        """Align Gemini transcription text with NeMo speaker segments."""
        if not self.speaker_segments:
            return gemini_segments

        structured = []
        for g_seg in gemini_segments:
            # Gemini might return [MM:SS] or seconds. We try to handle both.
            timestamp = g_seg.get('timestamp', '00:00')
            try:
                if ':' in timestamp:
                    m, s = map(int, timestamp.split(':'))
                    t_sec = m * 60 + s
                else:
                    t_sec = float(timestamp)
            except:
                t_sec = 0

            # Find best speaker for this timestamp
            best_speaker = "Unknown"
            for d_seg in self.speaker_segments:
                if d_seg['start'] <= t_sec <= d_seg['end']:
                    best_speaker = d_seg['speaker']
                    break
            
            structured.append({
                "speaker": best_speaker,
                "text": g_seg['text'],
                "timestamp": timestamp
            })
        return structured

    def transcribe_audio(self, audio_path=None):
        """Transcribe and Diarize using Gemini 3 Flash."""
        path = audio_path or self.audio_path
        if not path or not os.path.exists(path):
            logger.error("Transcription failed: No audio path provided.")
            return

        try:
            # 1. Upload to Gemini
            if not self.gemini_file:
                self.gemini_file = self._upload_to_gemini(path)
            
            if not self.gemini_file:
                raise Exception("Failed to upload audio to Gemini")

            # 2. Prompt for Transcription
            json_list = '[{"timestamp": "00:00", "text": "..."}]'
            prompt = f"""
            Transcribe the following audio file. 
            Include timestamps in format [MM:SS] for every speaker turn or significant pause.
            Important: Ensure full transcription word-for-word.
            Return the result ONLY as a JSON list of objects:
            {json_list}
            """
            
            logger.info("Requesting Gemini Transcription & Diarization...")
            response = self._generate_with_fallback(self.gemini_file, prompt)
            
            raw_text = response.text.strip()
            # Cleanup JSON
            raw_text = re.sub(r'^```json\n?', '', raw_text, flags=re.MULTILINE)
            raw_text = re.sub(r'```$', '', raw_text, flags=re.MULTILINE).strip()
            
            # Find JSON block
            json_match = re.search(r'\[.*\]', raw_text, re.DOTALL)
            if json_match:
                gemini_results = json.loads(json_match.group())
                logger.info(f"Gemini Transcription Complete: {len(gemini_results)} segments.")
                
                # Run NeMo Diarization now
                self.perform_diarization(path)
                
                # Align Gemini text with NeMo speakers
                self.structured_transcript = self._align_with_diarization(gemini_results)
            else:
                logger.error(f"Failed to parse Gemini transcription JSON. Raw response: {raw_text[:200]}...")
                self.structured_transcript = [{"speaker": "System", "text": "Transcription failed to format correctly.", "timestamp": "00:00"}]
        except Exception as e:
            logger.error(f"Gemini Transcription failed: {e}")
            self.structured_transcript = [{"speaker": "System", "text": f"Error: {str(e)}", "timestamp": "00:00"}]

    def generate_summary(self):
        """Analyze meeting using Gemini 3 Flash."""
        if not self.structured_transcript or (len(self.structured_transcript) == 1 and self.structured_transcript[0]['speaker'] == "System"):
            logger.error("No valid transcript to analyze.")
            self.intel = {"summary_en": "Transcription unavailable.", "summary_hi": "", "mom": [], "actions": []}
            return

        try:
            prompt = """
            Analyze the provided meeting transcript and return a JSON object with:
            - summary_en: Professional executive summary in English.
            - summary_hi: Accurate Hindi version of the summary.
            - mom: List of key discussion points.
            - actions: List of objects with keys: "task", "owner", "deadline".

            Output ONLY valid JSON.
            """
            
            logger.info("Generating Summary..." )
            
            transcript_text = "\n".join([f"{s.get('speaker', 'Unknown')} [{s.get('timestamp', '00:00')}]: {s.get('text', '')}" for s in self.structured_transcript])
            full_prompt = f"{prompt}\n\nTranscript:\n{transcript_text}"
            
            response = self._generate_with_fallback(full_prompt)
            raw = response.text.strip()
            
            raw = re.sub(r'^```json\n?', '', raw, flags=re.MULTILINE)
            raw = re.sub(r'```$', '', raw, flags=re.MULTILINE).strip()
            
            json_match = re.search(r'\{.*\}', raw, re.DOTALL)
            if json_match:
                self.intel = json.loads(json_match.group())
                logger.info("Gemini Analysis Complete")
            else:
                logger.error("Gemini returned invalid summary JSON")
                self.intel = {"summary_en": "Failed to parse analysis JSON.", "summary_hi": "", "mom": [], "actions": []}
        except Exception as e:
            logger.error(f"Gemini Summary failed: {e}")
            self.intel = {"summary_en": f"Summary failed: {str(e)}", "summary_hi": "", "mom": [], "actions": []}

    def export_to_pdf(self):
        stem = Path(self.audio_path).stem if self.audio_path else "Meeting"
        filename = f"{stem}_Renata_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        pdf_path = OUTPUT_DIR / filename

        try:
            # Page setup: letter with 0.75in margins on all sides
            PAGE_W, PAGE_H = letter
            MARGIN = 0.75 * inch
            CONTENT_W = PAGE_W - 2 * MARGIN   # usable width ≈ 7.0 inch

            doc = SimpleDocTemplate(
                str(pdf_path), pagesize=letter,
                leftMargin=MARGIN, rightMargin=MARGIN,
                topMargin=MARGIN, bottomMargin=MARGIN
            )
            styles = getSampleStyleSheet()

            # ── Style definitions ──────────────────────────────────────────
            title_style = ParagraphStyle(
                'RTitle', parent=styles['Heading1'],
                alignment=1, fontSize=18, spaceAfter=4,
                textColor=colors.HexColor("#1a1a2e")
            )
            subtitle_style = ParagraphStyle(
                'RSub', parent=styles['Normal'],
                alignment=1, fontSize=10, spaceAfter=20,
                textColor=colors.HexColor("#555555")
            )
            h2_style = ParagraphStyle(
                'RH2', parent=styles['Heading2'],
                fontSize=13, spaceBefore=18, spaceAfter=6,
                textColor=colors.HexColor("#2c3e50"),
                borderPad=4
            )
            normal_style = ParagraphStyle(
                'RNormal', parent=styles['Normal'],
                fontSize=10, leading=14, spaceAfter=4,
                wordWrap='CJK'
            )
            bullet_style = ParagraphStyle(
                'RBullet', parent=normal_style,
                leftIndent=12, firstLineIndent=-12, spaceAfter=3
            )
            # Hindi body — uses registered font if available, else Helvetica
            hindi_font = 'HindiFont' if HINDI_AVAILABLE else 'Helvetica'
            hindi_style = ParagraphStyle(
                'RHindi', parent=styles['Normal'],
                fontName=hindi_font, fontSize=11, leading=18,
                spaceAfter=6, wordWrap='CJK'
            )
            # Table cell style (wrapping)
            cell_style = ParagraphStyle(
                'RCell', parent=styles['Normal'],
                fontSize=9, leading=12, wordWrap='CJK'
            )
            header_cell_style = ParagraphStyle(
                'RHCell', parent=cell_style,
                fontName='Helvetica-Bold'
            )

            elements = []

            # ── Title block ────────────────────────────────────────────────
            elements.append(Paragraph(self.bot_name.upper(), title_style))
            elements.append(Paragraph(
                f"Meeting Report  •  {datetime.now().strftime('%B %d, %Y  |  %I:%M %p')}",
                subtitle_style
            ))
            elements.append(Spacer(1, 6))

            # Horizontal rule
            from reportlab.platypus import HRFlowable
            elements.append(HRFlowable(width="100%", thickness=1.5,
                                       color=colors.HexColor("#2c3e50"), spaceAfter=12))

            # ── Executive Summary ──────────────────────────────────────────
            summary_en = self.intel.get("summary_en", "").strip()
            if summary_en:
                elements.append(Paragraph("Executive Summary", h2_style))
                elements.append(Paragraph(summary_en, normal_style))

            # ── Hindi Summary ──────────────────────────────────────────────
            summary_hi = self.intel.get("summary_hi", "").strip()
            if summary_hi:
                # Heading in plain ASCII to avoid box characters
                elements.append(Paragraph("Summary (Hindi)", h2_style))
                elements.append(Paragraph(summary_hi, hindi_style))

            # ── Minutes of Meeting ─────────────────────────────────────────
            mom = self.intel.get("mom", [])
            if mom:
                elements.append(Paragraph("Minutes of Meeting", h2_style))
                for point in mom:
                    elements.append(Paragraph(f"• {point}", bullet_style))

            # ── Action Items table ─────────────────────────────────────────
            actions = self.intel.get("actions", [])
            if actions:
                elements.append(Paragraph("Action Items", h2_style))
                elements.append(Spacer(1, 4))

                # Column widths: Task=4.2in, Owner=1.4in, Deadline=1.4in  (total=7.0in)
                COL_TASK     = 4.2 * inch
                COL_OWNER    = 1.4 * inch
                COL_DEADLINE = CONTENT_W - COL_TASK - COL_OWNER

                header_row = [
                    Paragraph("Task",     header_cell_style),
                    Paragraph("Owner",    header_cell_style),
                    Paragraph("Deadline", header_cell_style),
                ]
                action_data = [header_row]
                for act in actions:
                    action_data.append([
                        Paragraph(act.get("task", ""),     cell_style),
                        Paragraph(act.get("owner", ""),    cell_style),
                        Paragraph(act.get("deadline", ""), cell_style),
                    ])

                action_table = Table(
                    action_data,
                    colWidths=[COL_TASK, COL_OWNER, COL_DEADLINE],
                    repeatRows=1
                )
                action_table.setStyle(TableStyle([
                    ('BACKGROUND',  (0, 0), (-1, 0),  colors.HexColor("#2c3e50")),
                    ('TEXTCOLOR',   (0, 0), (-1, 0),  colors.white),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1),
                     [colors.white, colors.HexColor("#f4f6f8")]),
                    ('GRID',        (0, 0), (-1, -1),  0.4, colors.HexColor("#cccccc")),
                    ('VALIGN',      (0, 0), (-1, -1),  'TOP'),
                    ('TOPPADDING',  (0, 0), (-1, -1),  5),
                    ('BOTTOMPADDING',(0, 0), (-1, -1), 5),
                    ('LEFTPADDING', (0, 0), (-1, -1),  6),
                    ('RIGHTPADDING',(0, 0), (-1, -1),  6),
                ]))
                elements.append(action_table)

            # ── Full Transcript ────────────────────────────────────────────
            if self.structured_transcript:
                elements.append(PageBreak())
                elements.append(Paragraph("Full Diarized Transcript", h2_style))
                elements.append(HRFlowable(width="100%", thickness=0.8,
                                           color=colors.HexColor("#cccccc"), spaceAfter=8))

                # Column widths: Time=0.65in, Speaker=1.1in, Text=rest
                COL_TIME    = 0.65 * inch
                COL_SPEAKER = 1.1  * inch
                COL_TEXT    = CONTENT_W - COL_TIME - COL_SPEAKER

                ts_header = [
                    Paragraph("Time",    header_cell_style),
                    Paragraph("Speaker", header_cell_style),
                    Paragraph("Text",    header_cell_style),
                ]
                trans_data = [ts_header]
                for s in self.structured_transcript:
                    trans_data.append([
                        Paragraph(s.get('timestamp', ''), cell_style),
                        Paragraph(s.get('speaker', ''),   cell_style),
                        Paragraph(s.get('text', ''),      cell_style),
                    ])

                trans_table = Table(
                    trans_data,
                    colWidths=[COL_TIME, COL_SPEAKER, COL_TEXT],
                    repeatRows=1
                )
                trans_table.setStyle(TableStyle([
                    ('BACKGROUND',  (0, 0), (-1, 0),  colors.HexColor("#2c3e50")),
                    ('TEXTCOLOR',   (0, 0), (-1, 0),  colors.white),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1),
                     [colors.white, colors.HexColor("#f4f6f8")]),
                    ('GRID',        (0, 0), (-1, -1),  0.3, colors.HexColor("#dddddd")),
                    ('VALIGN',      (0, 0), (-1, -1),  'TOP'),
                    ('TOPPADDING',  (0, 0), (-1, -1),  4),
                    ('BOTTOMPADDING',(0, 0), (-1, -1), 4),
                    ('LEFTPADDING', (0, 0), (-1, -1),  5),
                    ('RIGHTPADDING',(0, 0), (-1, -1),  5),
                ]))
                elements.append(trans_table)

            doc.build(elements)
            logger.info(f"PDF Report: {pdf_path}")
        except Exception as e:
            logger.error(f"PDF creation failed: {e}")
            traceback.print_exc()

    def calculate_analytics(self):
        """Calculate detailed meeting analytics from transcript and diarization"""
        if not self.structured_transcript:
            return

        logger.info("Calculating Meeting Analytics...")
        
        # 1. Speaker Time & Words
        speaker_data = {}
        total_duration = 0
        total_words = 0
        
        # Calculate duration from segments
        if self.speaker_segments:
            for seg in self.speaker_segments:
                spk = seg['speaker']
                dur = seg['end'] - seg['start']
                if spk not in speaker_data:
                    speaker_data[spk] = {"duration": 0, "words": 0}
                speaker_data[spk]["duration"] += dur
                total_duration += dur

        # Calculate words from transcript
        for entry in self.structured_transcript:
            spk = entry['speaker']
            text = entry.get('text', '')
            words = len(text.split())
            total_words += words
            if spk not in speaker_data:
                speaker_data[spk] = {"duration": 0, "words": 0}
            speaker_data[spk]["words"] += words

        # 2. Percentages & Engagement Score
        if total_duration > 0:
            for spk in speaker_data:
                speaker_data[spk]["percentage"] = round((speaker_data[spk]["duration"] / total_duration) * 100, 1)
                # Words Per Minute (WPM)
                dur_min = speaker_data[spk]["duration"] / 60
                speaker_data[spk]["wpm"] = round(speaker_data[spk]["words"] / dur_min, 1) if dur_min > 0 else 0
        
        # Total WPM for meeting
        tot_min = total_duration / 60
        avg_wpm = round(total_words / tot_min, 1) if tot_min > 0 else 0
        
        # Simple Engagement Score (0-100)
        # Based on: Number of speakers, word density, and turn-taking
        num_speakers = len(speaker_data)
        turns = len(self.structured_transcript)
        
        # Score = (Speakers * 10) + (Turns / 2) + (Words / 100)
        # Capped at 100
        engagement_score = min(100, (num_speakers * 15) + (turns / 4) + (total_words / 200))
        
        self.analytics = {
            "speaker_stats": speaker_data,
            "total_duration_sec": round(total_duration, 2),
            "total_words": total_words,
            "engagement_score": round(engagement_score, 1),
            "num_speakers": num_speakers
        }
        
        # Update intel for database storage
        self.intel["speaker_analytics"] = speaker_data
        self.intel["engagement_metrics"] = {
            "score": self.analytics["engagement_score"],
            "total_words": total_words
        }
        logger.info(f"Analytics: Score {engagement_score}, {num_speakers} Speakers detected.")

    def export_to_json(self):
        stem = Path(self.audio_path).stem if self.audio_path else "Meeting"
        filename = f"{stem}_RENA_Data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        json_path = OUTPUT_DIR / filename
        data = {
            "intelligence": self.intel,
            "transcript": self.structured_transcript
        }
        with open(json_path, 'w') as f:
            json.dump(data, f, indent=4)
        logger.info(f"JSON Data: {json_path}")

    def process_meeting(self, audio_path: str):
        """Hybrid Pipeline: Gemini 3 Flash (Transcription) + NVIDIA NeMo (Diarization)."""
        self.audio_path = audio_path
        
        # 1. Transcribe with Gemini
        self.transcribe_audio()

        # 2. Results are handled within transcribe_audio now (diarization called there)

        # 3. Analysis & Export
        self.calculate_analytics()
        self.generate_summary()
        self.export_to_pdf()
        self.export_to_json()
        logger.info("Hybrid Gemini + NeMo Pipeline Finished.")

# ==========================================================
# MAIN
# ==========================================================
if __name__ == "__main__":
    if len(sys.argv) > 1:
        generator = AdaptiveMeetingNotesGenerator(audio_path=sys.argv[1])
        generator.process_meeting(sys.argv[1])
    else:
        print("Usage: python meeting_notes_generator.py <audio_file.wav>")
