<div align="center">
  <h1>🤖 RENATA</h1>
  <p><strong>Advanced Meeting Intelligence Platform</strong></p>
  <p><em>Autonomous Agent · Multi-Stage AI Pipeline · Self-Hosted</em></p>
</div>

---

## What is Renata?

Renata is an end-to-end meeting intelligence platform. It autonomously joins your **Google Meet and Zoom** calls, records the audio, and runs it through a multi-stage AI pipeline powered entirely by **Google Gemini**. It delivers structured meeting intelligence — full transcripts, summaries, minutes of meeting (MOM), action items, speaker analytics, and a searchable knowledge base — all accessible from a responsive, premium web dashboard.

Built with **FastAPI** and **Jinja2**, RENATA is designed to be a lightweight, high-performance tool

---

## Core Features

### 🤖 Autonomous Bot
- Auto-joins scheduled meetings from **Google Calendar** at the exact start time.
- Supports **Google Meet** and **Zoom** via Playwright automation.
- Silent entry with camera off and mic muted.
- Auto-leaves when the meeting ends or stays empty for too long.
- Manual "Add to Live Meeting" trigger from the web dashboard.

### 🎙️ Gemini AI pipeline
- **Direct Gemini Processing**: Meeting recordings are uploaded to the Gemini File API for state-of-the-art long-context processing.
- **Transcription**: Uses `gemini-3-flash-preview` for word-for-word accuracy with timestamps.
- **Local Diarization**: NVIDIA NeMo TitaNet-L runs locally to accurately attribute speech to specific speakers.
- **Deep Intelligence**: Structured JSON generation for English/Hindi summaries, MOM, and actionable tasks.
- **Professional Reports**: Clean PDF exports with full Hindi font support.

### 📊 Intelligence Dashboard
- **Production-Ready Web UI**: Built with FastAPI and Jinja2 templates (replacing Streamlit).
- **Speaker Analytics**: Talk-time distribution, engagement scores, and pacing metrics.
- **Real-time Status**: Track upcoming, in-progress, and completed meetings on a unified timeline.

### 🔍 AI Search Assistant (RAG)
- **Unified Knowledge Base**: Sync your meeting archive into a `ChromaDB` vector store.
- **Gemini RAG Reasoning**: Ask anything about your past meetings and get precise answers powered by Gemini's reasoning over your private meeting data.
- **Auto-Sync**: One-click "Sync Knowledge Base" keeps your AI search always up to date.

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Framework** | FastAPI (Production Backend) |
| **Templates** | Jinja2 + Vanilla CSS (Midnight Theme) |
| **LLM / AI** | Google Gemini (Transcription, Synthesis, RAG) |
| **Diarization** | NVIDIA NeMo TitaNet-L (Local) |
| **Vector DB** | ChromaDB (RAG Storage) |
| **Embeddings** | sentence-transformers (`all-MiniLM-L6-v2`) |
| **Bot Automation** | Playwright + Playwright-Stealth |
| **Database** | SQLite (Thread-safe meetings & user storage) |
| **PDF Engine** | ReportLab (UTF-8 / Hindi support) |

---

## Installation

### Prerequisites
- Python **3.10 – 3.12**
- [FFmpeg](https://ffmpeg.org/download.html) (Audio processing)
- [VB-CABLE](https://vb-audio.com/Cable/) (Windows audio routing for bot capture)

### 1. Setup Environment
```bash
git clone https://github.com/Chandisha/RENATA_Notes_AI.git
cd RENATA_Notes_AI
python -m venv renata
# Windows: .\renata\Scripts\Activate.ps1 | Linux: source renata/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure Credentials
1. Place your Google `credentials.json` in the project root.
2. Initialize auth session (required for calendar sync):
   ```bash
   python renata_bot_pilot.py --auth-only
   ```
3. Set your Gemini API Key in `.env`:
   ```env
   GEMINI_API_KEY=your_key_here
   SESSION_SECRET=optional_random_string
   ```

---

## Usage

### 🚀 Running the Web App
```bash
uvicorn main:app --reload --port 8000
```
Visit **http://localhost:8000** to access the dashboard.

### 🤖 Running the Bot Separately
```bash
# Join a specific meeting now
python renata_bot_pilot.py "https://meet.google.com/xxx-xxxx-xxx"
```

### 📁 Pipeline Processor
```bash
# Process an existing audio file
python meeting_notes_generator.py "path/to/recording.wav"
```

---

## Project Structure
```
RENATA_Notes_AI/
├── main.py                    # FastAPI Production App
├── renata_bot_pilot.py        # Meeting Join Automation
├── meeting_notes_generator.py # Gemini AI Processing Pipeline
├── meeting_database.py        # SQLite Storage Layer
├── rag/                       # RAG Knowledge Base Logic
├── templates/                 # Jinja2 Layouts & Pages
├── static/                    # Global CSS Styles
├── fonts/                     # Hindi Support Assets
├── Procfile                   # Railway Deployment Config
└── requirements.txt           # Unified Dependency List
```

---

## Developer
**Chandisha Das** | [GitHub](https://github.com/Chandisha)

*"Building a future where every conversation becomes actionable intelligence."*
