import os
import json
import warnings
import sys
import time
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List

# --- AI LIBRARIES ---
from faster_whisper import WhisperModel
from loguru import logger

# 1. Google GenAI (Primary - Cloud)
try:
    from google import genai
    from google.genai import types
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False

# 2. Ollama (Fallback - Local)
try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False

# --- REPORTLAB (PDF) IMPORTS ---
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

warnings.filterwarnings("ignore")

# ==========================================
# 🔑 CONFIGURATION
# ==========================================
# GEMINI_API_KEY should be set in your Environment Variables for security.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# RECOMMENDATION: Use "qwen2.5:32b" for best intelligence.
OLLAMA_MODEL = "qwen2.5:32b" 

OUTPUT_DIR = Path("meeting_outputs")
OUTPUT_DIR.mkdir(exist_ok=True)
FONTS_DIR = Path(r"C:\Users\admin\Desktop\RENA-Meet\fonts") 

# --- CONFIGURE LOGGER ---
logger.remove()
logger.add(sys.stderr, format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>")

def setup_fonts():
    """Loads Hindi font for PDF support"""
    font_path = FONTS_DIR / "NotoSansDevanagari-Regular.ttf"
    if font_path.exists():
        try:
            pdfmetrics.registerFont(TTFont('HindiFont', str(font_path)))
            return True
        except: return False
    return False

HINDI_AVAILABLE = setup_fonts()

class AdaptiveMeetingNotesGenerator:
    def __init__(self, whisper_model="medium"):
        print("\n" + "="*60)
        logger.info(f"🔧 SYSTEM INIT | Model: {OLLAMA_MODEL}")
        print("="*60)

        # 1. SETUP GOOGLE
        self.google_client = None
        if GOOGLE_AVAILABLE:
            try:
                self.google_client = genai.Client(api_key=GEMINI_API_KEY)
                logger.info("   [Primary] Google Gemini Client Initialized.")
            except: pass

        # 2. SETUP OLLAMA
        if OLLAMA_AVAILABLE:
            try:
                ollama.list()
                logger.info(f"   [Fallback] Local Ollama Ready ({OLLAMA_MODEL}).")
            except:
                logger.warning("⚠️ Ollama not reachable. Run 'ollama serve' in terminal.")

        # 3. SETUP WHISPER
        logger.info(f"   [Audio] Loading Whisper ({whisper_model})...")
        try:
            self.whisper = WhisperModel(whisper_model, device="cpu", compute_type="int8")
            logger.info("   [Status] Whisper Ready.")
        except Exception as e:
            logger.error(f"❌ Whisper Failed: {e}")
            sys.exit(1)

    # --- STEP 1: TRANSCRIPTION ---
    def transcribe(self, audio_path: str) -> Dict:
        print("\n" + "-"*60)
        logger.info("🎙️ STEP 1: TRANSCRIPTION")
        print("-"*60)
        
        if not os.path.exists(audio_path):
            logger.error("Audio file does not exist.")
            return {"transcript": "", "segments": []}

        # Relaxed VAD parameters
        segments, _ = self.whisper.transcribe(
            audio_path,
            beam_size=5,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500) 
        )

        full_text = []
        transcript_segments = []
        
        print("   Processing Timeline: ", end="")
        has_speech = False
        
        for segment in segments:
            has_speech = True
            text = segment.text.strip()
            
            m, s = divmod(int(segment.start), 60)
            timestamp = f"{m:02d}:{s:02d}"
            
            transcript_segments.append({"timestamp": timestamp, "text": text})
            full_text.append(f"[{timestamp}] {text}")
            print("▓", end="", flush=True)
            
        print(" [Done]")
        
        if not has_speech:
            logger.warning("⚠️  NO SPEECH DETECTED.")
            return {"transcript": "", "segments": []}

        return {
            "transcript": "\n".join(full_text), 
            "segments": transcript_segments
        }

    # --- STEP 2: PIPELINE EXECUTION ---
    def analyze_transcript(self, transcript: str) -> Dict:
        print("\n" + "-"*60)
        logger.info("🧠 STEP 2: AI PIPELINE (Sum -> Hindi -> MOM -> Actions)")
        print("-"*60)
        
        if not transcript:
            return {"detected_context": "No Audio", "summary_en": "No speech detected.", "summary_hi": "-", "mom": [], "actions": []}

        # --- READ.AI REPLICATION PROMPT ---
        prompt = f"""
        You are an expert Meeting Intelligence Assistant (RENA AI). Your task is to perform a professional analysis of the following meeting transcript to replicate the exact experience of Read.ai.
        
        SOURCE TRANSCRIPT:
        {transcript[:50000]}
        
        YOUR ANALYSIS PIPELINE:
        1. **Executive Summary**: Write a strong 4-5 sentence summary in English, then translate it accurately into Hindi (Devanagari).
        2. **Meeting Chapters**: Thematic sections of the meeting. For each, identify the start timestamp and a brief summary.
        3. **Minutes (MOM)**: General high-level discussion points.
        4. **Action Plans**: Extract every task, who is responsible (Owner), and the deadline.
        5. **Sentiment Analysis**: Analyze the overall tone (Positive/Neutral/Negative) and provide a breakdown of participant sentiment.
        6. **Engagement Metrics**: Count questions asked, assess participant energy, and identify key recurring topics.
        7. **Coaching Analysis**: Evaluate the speaker's performance in three areas: 
           - **Clarity**: Estimate talking pace (words per minute) and count filler words.
           - **Inclusion**: Identify non-inclusive terms and provide a tip for improvement.
           - **Impact**: Detect any biases and score charisma level based on influence and positive delivery.

        OUTPUT FORMAT: Provide ONLY this JSON structure.
        {{
            "detected_context": "Main meeting topic",
            "summary_en": "Executive summary in English...",
            "summary_hi": "हिंदी में कार्यकारी सारांश...",
            "mom": ["Bullet point 1", "Bullet point 2"],
            "chapters": [
                {{ "title": "Topic Title", "start_time": "MM:SS", "summary": "Short chapter summary" }}
            ],
            "actions": [
                {{ "task": "Specific task", "owner": "Name/Team", "deadline": "MM/DD/YYYY or TBD" }}
            ],
            "sentiment_analysis": {{
                "overall": "Positive",
                "detail": "Detailed sentiment and tone analysis per speaker."
            }},
            "engagement_metrics": {{
                "questions_asked": 5,
                "filler_words_level": "Low/Medium/High",
                "key_questions": ["Question 1?", "Question 2?"]
            }},
            "speaker_analytics": [
                {{ "speaker": "Speaker 1", "tone": "Friendly/Direct", "contribution": "High/Low" }}
            ],
            "coaching_metrics": {{
                "clarity": {{
                    "talking_pace": "145 WPM",
                    "filler_words": ["um", "like", "actually"],
                    "filler_count": 12
                }},
                "inclusion": {{
                    "non_inclusive_terms": 0,
                    "tip": "Great job using gender-neutral language!"
                }},
                "impact": {{
                    "bias": "None",
                    "charisma_score": "High",
                    "charisma_detail": "Your tone was encouraging and fostered participation."
                }}
            }}
        }}
        """

        # 1. Try Gemini (Primary)
        if self.google_client:
            try:
                logger.info("   [Primary] Analyzing with Gemini 2.5 Flash...")
                response = self.google_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json")
                )
                logger.info("   [Success] Gemini analysis complete.")
                return json.loads(response.text)
            except Exception as e:
                logger.error(f"   ❌ Gemini Error: {e}")

        # 2. Try Local Ollama (Fallback)
        if OLLAMA_AVAILABLE:
            logger.info(f"   [Fallback] Running local analysis ({OLLAMA_MODEL})...")
            try:
                response = ollama.chat(model=OLLAMA_MODEL, messages=[
                    {'role': 'system', 'content': 'You are a JSON-only API. Output ONLY valid JSON.'},
                    {'role': 'user', 'content': prompt},
                ])
                
                raw = response['message']['content']
                clean = self._clean_json(raw)
                logger.info("   [Success] Local analysis complete.")
                return json.loads(clean)
            except Exception as e:
                logger.error(f"   ❌ Local AI Error: {e}")

        return {
            "detected_context": "Error", 
            "summary_en": "Analysis failed.", 
            "summary_hi": "-", 
            "mom": [], 
            "actions": [],
            "chapters": [],
            "sentiment_analysis": {},
            "engagement_metrics": {},
            "speaker_analytics": []
        }

    def _clean_json(self, text):
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1:
            return text[start:end+1]
        return text

    # --- STEP 3: PDF REPORT ---
    def generate_pdf(self, intel: Dict, segments: List[Dict], filename: str):
        print("\n" + "-"*60)
        logger.info("📄 STEP 3: GENERATING PDF")
        print("-"*60)
        
        pdf_path = OUTPUT_DIR / f"{filename}.pdf"
        
        try:
            doc = SimpleDocTemplate(str(pdf_path), pagesize=letter)
            styles = getSampleStyleSheet()
            
            # Custom Styles
            style_title = ParagraphStyle('T', parent=styles['Heading1'], fontSize=20, textColor=colors.navy, spaceAfter=20)
            style_h2 = ParagraphStyle('H2', parent=styles['Heading2'], fontSize=14, textColor=colors.black, spaceBefore=15, spaceAfter=5)
            style_body = ParagraphStyle('B', parent=styles['Normal'], fontSize=11, leading=14)
            style_hindi = ParagraphStyle('Hi', parent=styles['Normal'], fontSize=11, fontName='HindiFont' if HINDI_AVAILABLE else 'Helvetica')
            style_action = ParagraphStyle('Act', parent=styles['Normal'], fontSize=11, leading=14, leftIndent=10)

            elements = []

            # HEADER
            elements.append(Paragraph("MEETING INTELLIGENCE REPORT", style_title))
            elements.append(Paragraph(f"<b>Date:</b> {datetime.now().strftime('%Y-%m-%d %H:%M')}", style_body))
            elements.append(Spacer(1, 15))

            # 1. SUMMARY (ENG)
            elements.append(Paragraph("EXECUTIVE SUMMARY (English)", style_h2))
            elements.append(Paragraph(intel.get('summary_en', 'N/A'), style_body))
            
            # 2. SUMMARY (HINDI)
            elements.append(Paragraph("EXECUTIVE SUMMARY (Hindi)", style_h2))
            elements.append(Paragraph(intel.get('summary_hi', 'N/A'), style_hindi))
            elements.append(Spacer(1, 10))

            # 3. MOM
            if intel.get('mom'):
                elements.append(Paragraph("MINUTES OF MEETING", style_h2))
                for point in intel['mom']:
                    elements.append(Paragraph(f"• {point}", style_body))
                    elements.append(Spacer(1, 3))

            # 4. ACTION PLANS (Fixed Bullet Style)
            actions = intel.get('actions', [])
            if actions:
                logger.info(f"   [Actions] Found {len(actions)} action items. Adding to PDF...")
                elements.append(Spacer(1, 15))
                elements.append(Paragraph("ACTION PLANS & TASKS", style_h2))
                
                for a in actions:
                    task = a.get('task', 'No task description')
                    owner = a.get('owner', 'Unassigned')
                    deadline = a.get('deadline', 'TBD')
                    
                    # Format: • Task Name
                    #           (Owner: X | Deadline: Y)
                    text = f"• <b>{task}</b> <br/>&nbsp;&nbsp;&nbsp;<i>(Owner: {owner} | Deadline: {deadline})</i>"
                    
                    elements.append(Paragraph(text, style_action))
                    elements.append(Spacer(1, 8)) # Slightly more space between actions
            else:
                logger.info("   [Actions] No action items detected in transcript.")

            # 5. CHAPTERS (Thematic Segments)
            chaps = intel.get('chapters', [])
            if chaps:
                elements.append(Paragraph("MEETING CHAPTERS", style_h2))
                for c in chaps:
                    title = c.get('title', 'Topic')
                    start = c.get('start_time', '--:--')
                    elements.append(Paragraph(f"<b>[{start}] {title}</b>", style_body))
                    elements.append(Paragraph(c.get('summary', ''), style_body))
                    elements.append(Spacer(1, 6))

            # 6. SENTIMENT & ENGAGEMENT
            sent = intel.get('sentiment_analysis', {})
            if sent:
                elements.append(Paragraph("SENTIMENT & ENGAGEMENT", style_h2))
                stext = f"<b>Overall Sentiment:</b> {sent.get('overall', 'Neutral')}<br/>"
                stext += f"{sent.get('detail', '')}"
                elements.append(Paragraph(stext, style_body))
                
                eng = intel.get('engagement_metrics', {})
                if eng:
                    etext = f"<br/><b>Questions Asked:</b> {eng.get('questions_asked', 0)}<br/>"
                    etext += f"<b>Key Questions:</b> {', '.join(eng.get('key_questions', []))}"
                    elements.append(Paragraph(etext, style_body))

            # 7. TRANSCRIPT
            elements.append(PageBreak())
            elements.append(Paragraph("FULL TRANSCRIPT", style_h2))
            
            if not segments:
                elements.append(Paragraph("<i>(No audible speech detected in recording)</i>", style_body))
            else:
                for s in segments:
                    p = f"<b>[{s['timestamp']}]</b> {s['text']}"
                    elements.append(Paragraph(p, style_body))
                    elements.append(Spacer(1, 4))

            doc.build(elements)
            logger.info(f"   [File] Saved to: {pdf_path}")
            return str(pdf_path)

        except Exception as e:
            logger.error(f"❌ PDF Generation Error: {e}")
            import traceback
            traceback.print_exc()
            return None

    def process(self, audio_file):
        # 1. Transcribe
        res = self.transcribe(audio_file)
        
        # 2. Analyze
        intel = self.analyze_transcript(res['transcript'])
        
        # 3. Generate PDF
        filename = Path(audio_file).stem + "_report"
        final_pdf = self.generate_pdf(intel, res['segments'], filename)
        
        if final_pdf:
            # 4. Save to Database
            try:
                import meeting_database as db
                meeting_id = Path(audio_file).stem
                db.add_meeting(
                    meeting_id=meeting_id,
                    title=intel.get('detected_context', 'Meeting Analysis'),
                    start_time=datetime.now().isoformat(),
                    transcript_text=res['transcript'],
                    summary_text=intel.get('summary_en', ''),
                    action_items=intel.get('actions', []),
                    chapters=intel.get('chapters', []),
                    sentiment_analysis=intel.get('sentiment_analysis', {}),
                    engagement_metrics=intel.get('engagement_metrics', {}),
                    speaker_analytics=intel.get('speaker_analytics', []),
                    coaching_metrics=intel.get('coaching_metrics', {}),
                    pdf_path=str(final_pdf),
                    recording_path=str(audio_file)
                )
                logger.info(f"   [Database] Meeting saved to history.")
            except Exception as e:
                logger.error(f"❌ Database Save Error: {e}")
                
            print(f"\n🎉 SUCCESS! Report ready: {final_pdf}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        AdaptiveMeetingNotesGenerator().process(sys.argv[1])
    else:
        print("Usage: python meeting_notes_generator.py <file.wav>")