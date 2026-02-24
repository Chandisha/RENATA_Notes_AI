<div align="center">
  <h1>🤖 RENATA</h1>
  <p><strong>Enterprise Meeting Intelligence System</strong></p>
  <p>Your autonomous AI assistant that joins, records, transcribes, and summarizes every meeting — so you never miss a word.</p>
  ![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python)
  ![Streamlit](https://img.shields.io/badge/Dashboard-Streamlit-red?style=flat-square&logo=streamlit)
  ![Gemini](https://img.shields.io/badge/AI-Gemini%203%20Flash-purple?style=flat-square&logo=google)
  ![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)
</div>

---

## What is Renata?

Renata is an end-to-end meeting intelligence platform. It autonomously joins your **Google Meet and Zoom** calls, records the audio, and runs it through a multi-stage AI pipeline powered by **Google Gemini**. It delivers structured meeting intelligence — full transcripts, summaries, minutes of meeting (MOM), action items, speaker analytics, and a searchable knowledge base — all accessible from a premium web dashboard.

Think of it as your own self-hosted Read.ai, powered by Gemini.

---

## Core Features

### 🤖 Autonomous Bot

- Auto-joins scheduled meetings from **Google Calendar** at the exact start time
- Supports both **Google Meet** and **Zoom** (via web browser automation)
- Bot enters with camera off and mic muted — completely silent
- Auto-leaves when the meeting ends or the room is empty
- Manual "Add to Live Meeting" option from the dashboard

### 🎙️ AI Transcription & Analysis Pipeline

- **Audio Upload → Gemini**: The meeting recording is uploaded directly to Gemini's File API
- **Transcription**: **Gemini 3 Flash** (`gemini-3-flash-preview`) transcribes the full audio word-for-word with timestamps — falls back to **Gemini 2.5 Flash** if needed
- **Speaker Diarization**: **NVIDIA NeMo TitaNet-L** runs locally to detect who said what, then the speaker labels are aligned with the Gemini transcript
- **AI Analysis**: Gemini generates a structured JSON report with:
  - Executive Summary (English)
  - Summary in Hindi
  - Minutes of Meeting (MoM)
  - Action Items with owner & deadline
- **Export**: One-click PDF (with Hindi font support) and JSON export

### 📊 Analytics Dashboard

- Talk-time ratio and words-per-minute per speaker
- Engagement score (based on turns, speakers, and word density)
- Meeting history with live status tracking (Upcoming, In Progress, Completed)
- Aggregated analytics across all past meetings

### 🔍 AI Search Copilot (RAG)

- Ask natural language questions across all your past meeting reports
- Example: *"What budget was discussed in the Q4 planning meeting?"*
- Powered by `sentence-transformers` + `ChromaDB` vector store
- LLM reasoning via local **Ollama** (Gemma/Qwen 2.5)
- Full conversation memory per thread

### 🔌 Integrations Hub

- **Google Calendar**: Auto-detects and schedules the bot for upcoming meetings
- **Gmail**: Scans emails for meeting links and action items
- **Google Drive**: Search files for contextual document intelligence
- **Notion**: Push meeting summaries directly to your Notion workspace
- **Zoom**: Detect and join Zoom links from calendar or paste directly

---

## AI Pipeline — How It Works

┌─────────────────────────────────────────────────────────────┐  
│ RENATA AI PIPELINE │  
├─────────────────────────────────────────────────────────────┤  
│ 1. Bot joins meeting (Playwright automation) │  
│ 2. Audio captured via VB-CABLE / FFmpeg │  
│ 3. Audio uploaded to Gemini File API │  
│ 4. Gemini 3 Flash → Transcription (with timestamps) │  
│ └─ Fallback: Gemini 2.5 Flash │  
│ 5. NVIDIA NeMo TitaNet-L → Speaker Diarization (local) │  
│ 6. Speakers aligned to Gemini transcript │  
│ 7. Gemini 3 Flash → Summary, MoM, Action Items (JSON) │  
│ 8. Analytics calculated (talk-time, engagement, WPM) │  
│ 9. PDF + JSON exported to meeting_outputs/ │  
│ 10. Report indexed into ChromaDB for RAG Search │  
└─────────────────────────────────────────────────────────────┘  

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Dashboard** | Streamlit + Custom CSS (Glassmorphic Dark UI) |
| **Bot Automation** | Playwright + Playwright-Stealth |
| **Transcription** | Google Gemini 3 Flash (audio → text via Gemini File API) |
| **AI Analysis** | Google Gemini 3 Flash · Gemini 2.5 Flash (fallback) |
| **Speaker Diarization** | NVIDIA NeMo TitaNet-L (runs locally) |
| **RAG Search** | LangChain · ChromaDB · sentence-transformers |
| **RAG LLM** | Ollama (Qwen 2.5 / Gemma — local fallback) |
| **PDF Reports** | ReportLab + NotoSansDevanagari (Hindi support) |
| **Auth** | Google OAuth 2.0 |
| **Database** | SQLite (custom meeting_database.py) |
| **Audio Processing** | FFmpeg · VB-CABLE · librosa |
| **Language** | Python 3.11+ |

---

## Installation

### Prerequisites

- Python **3.10 – 3.12**
- [FFmpeg](https://ffmpeg.org/download.html) — audio recording and processing
- [VB-CABLE](https://vb-audio.com/Cable/) — virtual audio routing for bot capture (Windows)
- [Ollama](https://ollama.com/) *(optional)* — local LLM for RAG search

### 1. Clone the Repository

```bash
git clone https://github.com/Chandisha/RENATA_Notes_AI.git
cd RENATA_Notes_AI
```

### 2. Create & Activate Virtual Environment

```bash
python -m venv renata
# Windows
.\renata\Scripts\Activate.ps1
# macOS / Linux
source renata/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 4. Set Up Google Cloud Credentials

Go to Google Cloud Console  
Create a project → Enable Google Calendar API, Gmail API, Google Drive API, People API  
Create OAuth 2.0 Desktop App credentials → Download as credentials.json  
Place credentials.json in the project root  

### 5. Configure Environment Variables

```bash
cp .env.example .env
```

Open .env and fill in:

```env
GEMINI_API_KEY=your_gemini_api_key_from_google_ai_studio
```

Get your free key at aistudio.google.com

🔒 .env is in .gitignore — your keys are never uploaded.

---

## Usage

### 🖥️ Mode A: Web Dashboard (Recommended)

Full intelligence hub — calendar, analytics, AI search, and integrations:

```bash
streamlit run frontend.py
```

Sign in with Google on first launch. The bot will auto-pilot from here.

### 🤖 Mode B: Dispatch Bot to a Meeting Now

Send the bot to any Google Meet or Zoom link immediately:

```bash
python renata_bot_pilot.py "https://meet.google.com/xxx-xxxx-xxx"
python renata_bot_pilot.py "https://zoom.us/j/123456789"
```

### 📁 Mode C: Process an Existing Audio File

Run the full Gemini AI pipeline on a pre-recorded .wav file:

```bash
python meeting_notes_generator.py "path/to/recording.wav"
```

Output: PDF report + JSON data saved to meeting_outputs/

---

## Project Structure

```
RENATA_Notes_AI/
├── frontend.py                        # Streamlit Web Dashboard
├── renata_bot_pilot.py                # Autonomous Meeting Bot (Meet + Zoom)
├── meeting_notes_generator.py         # Gemini AI Pipeline & Report Engine
├── meeting_database.py                # SQLite Database Layer
├── integrations_service.py            # Google, Notion, Zoom Integrations
├── gmail_scanner_service.py           # Gmail Intelligence Scanner
├── rag_assistant.py                   # AI Search Copilot Interface
├── rag/                               # RAG Pipeline (Embeddings, VectorDB, LLM)
│   ├── config.py
│   ├── conversation.py
│   ├── document_processor.py
│   ├── embeddings.py
│   ├── llm_manager.py
│   ├── retriever.py
│   └── vector_store.py
├── components/
│   └── sidebar.py                     # Dashboard Sidebar Navigation
├── fonts/
│   └── NotoSansDevanagari-Regular.ttf # Hindi PDF Reports
├── meeting_outputs/                   # Reports, DB, recordings (gitignored)
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## Roadmap

Chrome Extension — "Join with Renata" button inside Google Meet  
Slack / Discord Push — Auto-send summaries to project channels  
Real-time Translation — Live meeting translation for global teams  
Microsoft Teams Support — Bot joining automation for Teams  
Gemini Live API — Real-time streaming transcription during calls  
Mobile Dashboard — React Native companion app  

---

## Security & Privacy

All credentials stored in a local .env file — never hardcoded or uploaded  
token.json and credentials.json are in .gitignore  
Meeting recordings stored locally in meeting_outputs/ — not sent to any third-party cloud storage  
Audio is uploaded temporarily to Gemini File API for transcription and auto-deleted after processing  
Google OAuth scopes are minimal: Calendar (read), Gmail (read), Drive (read)  

---

## Developer

Chandisha Das  
github.com/Chandisha  

"Building a future where every conversation becomes actionable intelligence."

Version: 1.0.0 · License: MIT

Good  
Bad  
Review Changes
