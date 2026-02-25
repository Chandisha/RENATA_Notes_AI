<div align="center">
  <h1>🤖 RENATA</h1>
  <p><strong>Enterprise Meeting Intelligence Platform</strong></p>
  <p><em>Multi-User Architecture · OAuth 2.0 Flows · Multi-Stage AI Pipeline</em></p>
</div>

---

## What is Renata?

Renata is a premium, multi-user meeting intelligence platform. It autonomously joins your **Google Meet and Zoom** calls, records the audio, and runs it through a multi-stage AI pipeline powered by **Google Gemini**. It delivers structured meeting intelligence — full transcripts, summaries, minutes of meeting (MOM), action items, speaker analytics, and a searchable knowledge base — all isolated per user and accessible from a high-performance web dashboard.

Built with **FastAPI**, **SQLite**, and **OAuth 2.0**, RENATA is designed to be a secure, scalable, and self-hosted alternative to enterprise tools like Read.ai.

---

## New in v1.1: Multi-User & Deep Integrations

### 👥 Secure Multi-User Core
- **Data Isolation**: Every user has their own secure profile. Meetings, transcripts, and analytics are private and isolated by user email.
- **Personalized Experience**: Individual settings for bot names, recording preferences, and language synthesis.

### 🔐 Modern OAuth 2.0 Flows
- **Google Sign-In**: Securely authenticate with your Google account. No manual token management required.
- **Zoom Direct Connect**: Link your Zoom account via OAuth to allow RENATA to manage meetings directly from your Zoom host profile.

### 🌐 Integrations Hub
- A centralized dashboard to manage your connections to **Google Calendar, Gmail, Google Drive, and Zoom**.
- Real-time connection status and quick-launch actions for each service.

---

## Core Features

### 🤖 Autonomous Bot
- Auto-joins scheduled meetings from **Google Calendar** at the exact start time.
- Supports **Google Meet** and **Zoom** via Playwright automation.
- Silent entry with camera off and mic muted.
- Auto-leaves when the meeting ends or stays empty for too long.
- Manual "Add to Live Meeting" trigger with per-user context.

### 🎙️ Gemini AI pipeline
- **Direct Gemini Processing**: Meeting recordings are uploaded to the Gemini File API for state-of-the-art long-context processing.
- **Transcription**: Uses `gemini-1.5-flash` for word-for-word accuracy with timestamps.
- **Local Diarization**: NVIDIA NeMo TitaNet-L runs locally to accurately attribute speech to specific speakers.
- **Deep Intelligence**: Structured JSON generation for English/Hindi summaries, MOM, and actionable tasks.
- **Professional Reports**: Clean PDF exports with full Hindi font support.

### 📊 Intelligence Dashboard
- **Production-Ready Web UI**: High-performance FastAPI backend with Jinja2 templates.
- **Speaker Analytics**: Talk-time distribution, engagement scores, and pacing metrics.
- **Real-time Status**: Track upcoming, in-progress, and completed meetings on a unified timeline.

### 🔍 AI Search Assistant (RAG)
- **Unified Knowledge Base**: Sync your meeting archive into a `ChromaDB` vector store.
- **Gemini RAG Reasoning**: Ask anything about your past meetings and get precise answers powered by Gemini's reasoning over your private, user-scoped data.

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Framework** | FastAPI (Production Backend) |
| **Auth** | OAuth 2.0 (Google, Zoom) |
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
Create a `.env` file in the root directory:
```env
# AI & Database
GEMINI_API_KEY=your_gemini_key
SESSION_SECRET=a_random_secure_string

# Zoom OAuth (Optional)
ZOOM_CLIENT_ID=your_zoom_id
ZOOM_CLIENT_SECRET=your_zoom_secret
```

*Note: For Google Login, ensure your `credentials.json` from Google Cloud Console is placed in the project root.*

---

## Usage

### 🚀 Running the Web App
```bash
uvicorn main:app --reload --port 8000
```
Visit **http://localhost:8000** to access the dashboard.

### 🤖 Running the Bot Manually
```bash
# Join a specific meeting for a specific user
python renata_bot_pilot.py "https://meet.google.com/xxx-xxxx-xxx" --user "user@email.com"
```

---

## Project Structure
```
RENATA_Notes_AI/
├── main.py                    # FastAPI Production App & OAuth Handlers
├── renata_bot_pilot.py        # Meeting Join Automation (User-Aware)
├── meeting_notes_generator.py # Gemini AI Processing Pipeline
├── meeting_database.py        # SQLite Multi-User Storage Layer
├── rag/                       # RAG Knowledge Base Logic
├── templates/                 # Jinja2 Layouts & Pages
├── static/                    # Global CSS Styles
└── requirements.txt           # Unified Dependency List
```

---

## Developer
**Chandisha Das** | [GitHub](https://github.com/Chandisha)

*"Building a future where every conversation becomes actionable intelligence."*
