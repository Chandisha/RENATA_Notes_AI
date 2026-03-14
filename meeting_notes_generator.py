import os
import re
import json
import warnings
import sys
import torch
import time
import base64
import traceback
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from loguru import logger
from dotenv import load_dotenv

# Internal imports
import config
import meeting_database as db

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
warnings.filterwarnings("ignore", category=FutureWarning)

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
        self.last_transcripts_pdf_path = None
        self.meeting_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.last_json_path = None

    def _generate_with_fallback(self, content, prompt_text=None):
        """Use Gemini 3 Flash (Preview) as primary, Gemini 2.5 Flash (Stable) as fallback."""
        models_to_try = [
            "gemini-3-flash-preview",   # Gemini 3 Flash — frontier performance
            "gemini-2.5-flash",         # Gemini 2.5 Flash — stable GA fallback
        ]
        
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
        
        raise Exception("All requested Gemini models failed.")

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
        """Disabled local NeMo diarization as per user request to use purely Gemini."""
        logger.info("Local NeMo Diarization skipped (Pure Gemini Mode).")
        return

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
You are transcribing a meeting recording. Follow these rules STRICTLY:

1. TRANSCRIBE EVERY WORD from the very beginning of the audio to the very end. Do NOT skip silent parts at the start - include everything.
2. Use RELATIVE timestamps starting from 00:00 (beginning of the audio file), in MM:SS format.
3. Identify different speakers as Speaker A, Speaker B, etc.
4. VERY IMPORTANT - Language: The speakers may speak a mix of Hindi and English (Hinglish).
   - Write English words in English as-is.
   - Write Hindi words using Roman script transliteration (e.g., 'aap kaise hain', 'theek hai', 'hoga').
   - Do NOT use Devanagari script (no Hindi Unicode characters like \u0900-\u097F).
5. Return ONLY a valid JSON array. No markdown, no explanation.

Output format:
[{"timestamp": "00:00", "speaker": "Speaker A", "text": "hello theek hai, let's start the meeting"}, ...]
"""
            
            logger.info("Requesting Gemini Hinglish Transcription & Diarization...")
            response = self._generate_with_fallback(self.gemini_file, prompt)
            
            raw_text = response.text.strip()
            # Strip markdown code fences if present
            if raw_text.startswith('```'):
                raw_text = re.sub(r'^```[a-z]*\n?', '', raw_text)
                raw_text = re.sub(r'\n?```$', '', raw_text.strip())
            
            json_match = re.search(r'\[.*\]', raw_text, re.DOTALL)
            if json_match:
                self.structured_transcript = json.loads(json_match.group())
                logger.info(f"Gemini Transcription Complete: {len(self.structured_transcript)} segments.")
            else:
                logger.error("Failed to parse Gemini transcription JSON. Raw response:")
                logger.error(raw_text[:500])
        except Exception as e:
            logger.error(f"Gemini Transcription failed: {e}")

    def generate_summary(self):
        if not self.structured_transcript: return

        try:
            prompt = """
            Analyze the following meeting transcript and return a JSON object with:
            - title: A short, descriptive title for the meeting (max 6-8 words).
            - summary_en: Professional executive summary in English.
            - summary_hi: Careful Hindi version of the summary (Devanagari).
            - mom: List of key discussion points in English.
            - actions: List of objects in English with keys: "task", "owner", "deadline".
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
                
                # Update database title if AI generated a better one
                if self.intel.get('title'):
                    logger.info(f"AI Project Title: {self.intel['title']}")
                logger.info("Gemini Analysis Complete")
        except Exception as e:
            logger.error(f"Gemini Summary failed: {e}")

    def export_to_pdf(self):
        stem = Path(self.audio_path).stem if self.audio_path else "Meeting"
        filename = f"{stem}_Renata_Report_{self.meeting_timestamp}.pdf"
        pdf_path = OUTPUT_DIR / filename
        self.last_pdf_path = str(pdf_path)

        def safe_text(txt):
            """Remove or replace non-ASCII characters to prevent black boxes in standard PDF fonts.
            Allows common Latin punctuation. Hindi words should already be in Roman script from Gemini.
            """
            if not txt: return ""
            result = []
            for c in str(txt):
                if ord(c) < 128:
                    result.append(c)
                else:
                    # Replace non-ASCII with closest ASCII or just a space
                    result.append(' ')
            return ''.join(result).strip()

        try:
            PAGE_W, PAGE_H = letter
            MARGIN = 0.75 * inch
            CONTENT_W = PAGE_W - 2 * MARGIN
            doc = SimpleDocTemplate(str(pdf_path), pagesize=letter, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=MARGIN)
            styles = getSampleStyleSheet()

            title_style = ParagraphStyle('RTitle', parent=styles['Heading1'], alignment=1, fontSize=22, spaceAfter=8, textColor=colors.HexColor("#2563eb"))
            h2_style = ParagraphStyle('RH2', parent=styles['Heading2'], fontSize=14, spaceBefore=20, spaceAfter=8, textColor=colors.HexColor("#1e40af"), borderPadding=4, borderSide="bottom", borderWidth=0.5, borderColor=colors.HexColor("#bfdbfe"))
            normal_style = ParagraphStyle('RNormal', parent=styles['Normal'], fontSize=10, leading=15, textColor=colors.HexColor("#334155"))
            hindi_style = ParagraphStyle('RHindi', parent=styles['Normal'], fontName='HindiFont' if HINDI_AVAILABLE else 'Helvetica', fontSize=11, leading=18, textColor=colors.HexColor("#1e293b"))
            cell_style = ParagraphStyle('RCell', parent=styles['Normal'], fontSize=9, leading=13, textColor=colors.HexColor("#475569"))

            elements = []
            # Modern Header
            header_table_data = [[
                Paragraph(safe_text(self.bot_name.upper()), ParagraphStyle('BName', parent=title_style, alignment=0, fontSize=20)),
                Paragraph(f"Intelligence Report<br/>{datetime.now().strftime('%B %d, %Y')}", ParagraphStyle('RDate', parent=normal_style, alignment=2, fontSize=9))
            ]]
            header_table = Table(header_table_data, colWidths=[CONTENT_W*0.7, CONTENT_W*0.3])
            header_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'BOTTOM'), ('BOTTOMPADDING', (0,0), (-1,-1), 12)]))
            elements.append(header_table)
            
            # Decorative Line
            elements.append(Table([[""]], colWidths=[CONTENT_W], rowHeights=[2], style=TableStyle([('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#2563eb"))])))
            elements.append(Spacer(1, 18))

            if self.intel.get("summary_en"):
                elements.append(Paragraph("Executive Summary", h2_style))
                elements.append(Paragraph(safe_text(self.intel["summary_en"]), normal_style))

            if self.intel.get("summary_hi"):
                elements.append(Paragraph("Summary (Hindi)", h2_style))
                # Summary Hindi still uses HindiFont if possible, otherwise Helvetica
                elements.append(Paragraph(self.intel["summary_hi"], hindi_style))

            if self.intel.get("mom"):
                elements.append(Paragraph("Minutes of Meeting", h2_style))
                for p in self.intel["mom"]: elements.append(Paragraph(f"• {safe_text(p)}", normal_style))

            actions = self.intel.get("actions", [])
            if actions:
                elements.append(Paragraph("Action Items", h2_style))
                action_data = [["Task", "Owner", "Deadline"]]
                for act in actions: action_data.append([safe_text(act.get("task","")), safe_text(act.get("owner","")), safe_text(act.get("deadline",""))])
                t = Table(action_data, colWidths=[CONTENT_W*0.6, CONTENT_W*0.2, CONTENT_W*0.2])
                t.setStyle(TableStyle([
                    ('BACKGROUND',(0,0),(-1,0),colors.HexColor("#f1f5f9")), 
                    ('TEXTCOLOR',(0,0),(-1,0),colors.HexColor("#1e40af")), 
                    ('GRID',(0,0),(-1,-1),0.5,colors.HexColor("#cbd5e1")),
                    ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                    ('TOPPADDING', (0,0), (-1,-1), 6),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 6),
                ]))
                elements.append(t)

            if self.structured_transcript:
                elements.append(PageBreak())
                elements.append(Paragraph("Full Transcript (Hinglish - Roman Script)", h2_style))
                elements.append(Paragraph(
                    "Hindi words are written in Roman transliteration. English words appear as spoken.",
                    ParagraphStyle('note', parent=styles['Normal'], fontSize=8, textColor=colors.grey, spaceAfter=8)
                ))
                trans_data = [["Time", "Speaker", "Text"]]
                for s in self.structured_transcript:
                    trans_data.append([
                        Paragraph(safe_text(s.get('timestamp','')), cell_style),
                        Paragraph(safe_text(s.get('speaker','')), ParagraphStyle('RSpeak', parent=cell_style, fontName='Helvetica-Bold')),
                        Paragraph(safe_text(s.get('text','')), normal_style)
                    ])
                t = Table(trans_data, colWidths=[CONTENT_W*0.12, CONTENT_W*0.18, CONTENT_W*0.7])
                t.setStyle(TableStyle([
                    ('BACKGROUND',(0,0),(-1,0),colors.HexColor("#f8fafc")), 
                    ('TEXTCOLOR',(0,0),(-1,0),colors.HexColor("#475569")),
                    ('GRID',(0,0),(-1,-1),0.1,colors.HexColor("#e2e8f0")),
                    ('VALIGN',(0,0),(-1,-1),'TOP'),
                    ('TOPPADDING', (0,0), (-1,-1), 4),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 4),
                ]))
                elements.append(t)

            doc.build(elements)
            logger.info(f"PDF Exported: {pdf_path}")
        except Exception as e:
            logger.error(f"PDF Export failed: {e}")

    def export_transcripts_pdf(self):
        stem = Path(self.audio_path).stem if self.audio_path else "Meeting"
        filename = f"{stem}_Renata_Transcripts_{self.meeting_timestamp}.pdf"
        pdf_path = OUTPUT_DIR / filename
        self.last_transcripts_pdf_path = str(pdf_path)

        def safe_text(txt):
            if not txt: return ""
            result = []
            for c in str(txt):
                if ord(c) < 128:
                    result.append(c)
                else:
                    result.append(' ')
            return ''.join(result).strip()

        try:
            PAGE_W, PAGE_H = letter
            MARGIN = 0.75 * inch
            CONTENT_W = PAGE_W - 2 * MARGIN
            doc = SimpleDocTemplate(str(pdf_path), pagesize=letter, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=MARGIN)
            styles = getSampleStyleSheet()

            title_style = ParagraphStyle('RTitle', parent=styles['Heading1'], alignment=1, fontSize=22, spaceAfter=8, textColor=colors.HexColor("#2563eb"))
            h2_style = ParagraphStyle('RH2', parent=styles['Heading2'], fontSize=14, spaceBefore=20, spaceAfter=8, textColor=colors.HexColor("#1e40af"), borderPadding=4, borderSide="bottom", borderWidth=0.5, borderColor=colors.HexColor("#bfdbfe"))
            normal_style = ParagraphStyle('RNormal', parent=styles['Normal'], fontSize=10, leading=15, textColor=colors.HexColor("#334155"))
            cell_style = ParagraphStyle('RCell', parent=styles['Normal'], fontSize=9, leading=13, textColor=colors.HexColor("#475569"))

            elements = []
            header_table_data = [[
                Paragraph(safe_text(self.bot_name.upper()), ParagraphStyle('BName', parent=title_style, alignment=0, fontSize=20)),
                Paragraph(f"Transcripts Report<br/>{datetime.now().strftime('%B %d, %Y')}", ParagraphStyle('RDate', parent=normal_style, alignment=2, fontSize=9))
            ]]
            header_table = Table(header_table_data, colWidths=[CONTENT_W*0.7, CONTENT_W*0.3])
            header_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'BOTTOM'), ('BOTTOMPADDING', (0,0), (-1,-1), 12)]))
            elements.append(header_table)
            
            elements.append(Table([[""]], colWidths=[CONTENT_W], rowHeights=[2], style=TableStyle([('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#2563eb"))])))
            elements.append(Spacer(1, 18))

            if self.structured_transcript:
                elements.append(Paragraph("Full Transcript", h2_style))
                trans_data = [["Time", "Speaker", "Text"]]
                for s in self.structured_transcript:
                    trans_data.append([
                        Paragraph(safe_text(s.get('timestamp','')), cell_style),
                        Paragraph(safe_text(s.get('speaker','')), ParagraphStyle('RSpeak', parent=cell_style, fontName='Helvetica-Bold')),
                        Paragraph(safe_text(s.get('text','')), normal_style)
                    ])
                t = Table(trans_data, colWidths=[CONTENT_W*0.12, CONTENT_W*0.18, CONTENT_W*0.7])
                t.setStyle(TableStyle([
                    ('BACKGROUND',(0,0),(-1,0),colors.HexColor("#f8fafc")), 
                    ('TEXTCOLOR',(0,0),(-1,0),colors.HexColor("#475569")),
                    ('GRID',(0,0),(-1,-1),0.1,colors.HexColor("#e2e8f0")),
                    ('VALIGN',(0,0),(-1,-1),'TOP'),
                    ('TOPPADDING', (0,0), (-1,-1), 4),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 4),
                ]))
                elements.append(t)
            else:
                elements.append(Paragraph("No transcripts available.", normal_style))

            doc.build(elements)
            logger.info(f"Transcripts PDF Exported: {pdf_path}")
        except Exception as e:
            logger.error(f"Transcripts PDF Export failed: {e}")

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
        self.export_transcripts_pdf()
        
        # Save JSON
        data = {"intelligence": self.intel, "transcript": self.structured_transcript}
        json_path = OUTPUT_DIR / f"{Path(audio_path).stem}_data.json"
        with open(json_path, 'w') as f: json.dump(data, f, indent=4)
        self.last_json_path = str(json_path)
        logger.info("Gemini Hybrid Pipeline Finished.")

def process_meeting_audio(audio_path: str, meeting_id: str):
    """
    Standard entry point for the bot pilot to process a recording.
    """
    logger.info(f"Starting pipeline for meeting {meeting_id} with audio {audio_path}")
    generator = AdaptiveMeetingNotesGenerator(audio_path)
    try:
        generator.process_meeting(audio_path)
        
        # Read PDFs for blob storage (Vercel support)
        pdf_blob = None
        transcripts_pdf_blob = None
        
        try:
            if generator.last_pdf_path and os.path.exists(generator.last_pdf_path):
                with open(generator.last_pdf_path, "rb") as f:
                    pdf_blob = base64.b64encode(f.read()).decode('utf-8')
            
            if generator.last_transcripts_pdf_path and os.path.exists(generator.last_transcripts_pdf_path):
                with open(generator.last_transcripts_pdf_path, "rb") as f:
                    transcripts_pdf_blob = base64.b64encode(f.read()).decode('utf-8')
        except Exception as e:
            logger.error(f"Error encoding PDF blobs: {e}")

        # Save results to database
        db.save_meeting_results(
            meeting_id,
            transcript=json.dumps(generator.structured_transcript),
            summary=generator.intel.get("summary_en", ""),
            action_items=json.dumps(generator.intel.get("actions", [])),
            speaker_stats=json.dumps(generator.intel.get("speaker_analytics", {})),
            engagement=json.dumps(generator.intel.get("engagement_metrics", {})),
            pdf_path=generator.last_pdf_path,
            transcripts_pdf_path=generator.last_transcripts_pdf_path,
            pdf_blob=pdf_blob,
            transcripts_pdf_blob=transcripts_pdf_blob,
            json_path=generator.last_json_path
        )
        logger.info(f"Pipeline results saved to DB for {meeting_id}")
        
        # Email the transcript explicitly
        # Email the meeting report (HTML version)
        try:
            mtg = db.get_meeting(meeting_id)
            if mtg and mtg.get('user_email'):
                user_email = mtg['user_email']
                # Use AI generated title if available, otherwise fallback to database title
                title = generator.intel.get('title') or mtg.get('title') or 'Live Meeting'
                meeting_date = datetime.now().strftime("%B %d, %Y")
                meeting_time = datetime.now().strftime("%I:%M %p")
                full_timestamp = f"{meeting_date} @ {meeting_time}"
                
                summary_text = generator.intel.get("summary_en", "Processing complete. Please find the attached report.")
                
                import smtplib
                from email.message import EmailMessage
                from email.utils import formataddr
                
                msg = EmailMessage()
                # Professional subject like the screenshot: [Dynamic Title] on [Date] @ [Time] | Meeting Report
                msg['Subject'] = f"{title.upper()} on {full_timestamp} | Read Meeting Report"
                msg['From'] = formataddr(("Renata Assistant", "daschandisha@gmail.com"))
                msg['To'] = user_email
                
                # Plain text version
                msg.set_content(f"Hi there,\n\nRenata has finished processing your meeting '{title}'.\n\nSUMMARY:\n{summary_text}\n\nPlease find the attached reports for details.\n\nBest,\nRenata AI")
                
                # Professional HTML version (Read AI style)
                action_items = generator.intel.get("actions", [])
                actions_html = ""
                if action_items:
                    actions_html = "<h3>Action Items</h3><ul>"
                    for item in action_items:
                        actions_html += f"<li>{item}</li>"
                    actions_html += "</ul>"

                html_content = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <style>
                        body {{ font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #1e293b; margin: 0; padding: 0; }}
                        .container {{ max-width: 600px; margin: 20px auto; padding: 30px; border: 1px solid #e2e8f0; border-radius: 16px; background: #ffffff; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }}
                        .header {{ text-align: center; margin-bottom: 25px; }}
                        .logo {{ width: 60px; height: 60px; border-radius: 50%; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
                        .brand {{ font-size: 14px; font-weight: 700; color: #8b5cf6; margin-top: 8px; text-transform: uppercase; letter-spacing: 1px; }}
                        .status-pill {{ display: inline-block; padding: 4px 12px; background: rgba(139, 92, 246, 0.1); color: #8b5cf6; border-radius: 20px; font-size: 11px; font-weight: 700; margin-bottom: 10px; }}
                        .meeting-title {{ font-size: 28px; font-weight: 800; color: #0f172a; margin: 5px 0 5px 0; text-align: center; }}
                        .meeting-date {{ font-size: 16px; color: #64748b; margin-bottom: 30px; text-align: center; }}
                        .summary-section {{ background: #f8fafc; padding: 25px; border-radius: 12px; border-left: 4px solid #8b5cf6; margin-bottom: 25px; }}
                        .summary-text {{ font-size: 15px; color: #334155; white-space: pre-wrap; }}
                        .actions-section {{ margin-bottom: 25px; }}
                        .actions-section h3 {{ font-size: 18px; color: #0f172a; border-bottom: 1px solid #f1f5f9; padding-bottom: 8px; margin-bottom: 15px; }}
                        .actions-section ul {{ padding-left: 20px; }}
                        .actions-section li {{ margin-bottom: 8px; font-size: 14px; color: #475569; }}
                        .button-container {{ margin-top: 30px; text-align: center; }}
                        .button {{ background: #8b5cf6; color: white !important; padding: 12px 25px; text-decoration: none; border-radius: 8px; font-weight: 600; display: inline-block; }}
                        .footer {{ margin-top: 40px; text-align: center; font-size: 12px; color: #94a3b8; border-top: 1px solid #f1f5f9; padding-top: 20px; }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <img src="https://renata-notes-ai.vercel.app/static/renataiot_logo.jpg" class="logo" alt="Renata Logo">
                            <div class="brand">Renata AI</div>
                        </div>
                        
                        <div style="text-align: center;">
                            <span class="status-pill">MEETING COMPLETE</span>
                            <h1 class="meeting-title">{title.upper()}</h1>
                            <div class="meeting-date">{full_timestamp}</div>
                        </div>
                        
                        <div class="summary-section">
                            <div class="summary-text">{summary_text}</div>
                        </div>

                        <div class="actions-section">
                            {actions_html}
                        </div>
                        
                        <div class="button-container">
                            <a href="https://renata-notes-ai.vercel.app/#dashboard" class="button">View Fully Categorized PDF Report</a>
                        </div>
                        
                        <div class="footer">
                            Powered by Renata Meeting Intelligence • Google Gemini 1.5 Flash<br>
                            You received this because Renata Assistant joined your meeting.
                        </div>
                    </div>
                </body>
                </html>
                """
                msg.add_alternative(html_content, subtype='html')
                
                # Attach Main Report PDF
                if generator.last_pdf_path and os.path.exists(generator.last_pdf_path):
                    with open(generator.last_pdf_path, 'rb') as f:
                        msg.add_attachment(f.read(), maintype='application', subtype='pdf', 
                                         filename=os.path.basename(generator.last_pdf_path))
                                         
                # Attach Transcript PDF
                if generator.last_transcripts_pdf_path and os.path.exists(generator.last_transcripts_pdf_path):
                    with open(generator.last_transcripts_pdf_path, 'rb') as f:
                        msg.add_attachment(f.read(), maintype='application', subtype='pdf', 
                                         filename=os.path.basename(generator.last_transcripts_pdf_path))
                
                logger.info(f"Sending professional report email to {user_email}...")
                with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
                    smtp.login("daschandisha@gmail.com", "bejh mcgq aibo zpfg")
                    smtp.send_message(msg)
                
                logger.info(f"Successfully emailed report to {user_email}")
        except Exception as e:
            logger.error(f"Failed to email transcript to user: {e}")
            traceback.print_exc()
            
    except Exception as e:
        logger.error(f"Pipeline failed for {meeting_id}: {e}")
        traceback.print_exc()
        db.update_bot_status(meeting_id, "FAILED", note=str(e))
        raise e

if __name__ == "__main__":
    if len(sys.argv) > 1:
        generator = AdaptiveMeetingNotesGenerator(audio_path=sys.argv[1])
        generator.process_meeting(sys.argv[1])
    else:
        print("Usage: python meeting_notes_generator.py <audio_file.wav>")
