# RENA - Enterprise Meeting Intelligence System (v1.0)

**RENA** is a comprehensive AI orchestration suite designed to transform meetings into actionable intelligence. By combining real-time browser automation with deep neural analysis, RENA automates the entire lifecycle of a meeting—from joining and recording to synthesizing executive-level reports and analytics.

---

## Core Features

### 1. Meeting & AI Assistant (The Core)
- **Autonomous RENA Bot**: Automatically joins scheduled meetings via Google Meet & Zoom.
- **Live Audio Capture**: Multi-source audio routing to capture high-fidelity meeting dialogue.
- **Neural Transcription**: Real-time Speech-to-Text powered by Faster-Whisper with multi-language support.
- **Speaker Fingerprinting**: Basic speaker detection to identify who said what.
- **Intelligence Reports**: Auto-generation of Summaries, Minutes of Meeting (MOM), and Key Highlights.

### 2. Advanced Analytics
- **Talk-Time Ratio**: Detailed breakdown of speaking time per participant.
- **Meeting Metrics**: Tracking total duration and word counts.
- **Engagement Score**: Rule-based analysis of meeting energy and interaction quality.

### 3. AI Search & Copilot
- **Meeting RAG**: Ask AI specific questions about past meetings (e.g., "What was the budget discussed last month?").
- **Semantic Search**: Find meetings by keywords or thematic context.
- **Interactive Transcript**: Viewer with timestamp jumps and keyword highlighting.

### 4. Dashboard & Collaboration
- **Web Intelligence Hub**: A premium Streamlit-powered dashboard for managing all meeting history.
- **One-Click Export**: Export summaries to PDF or JSON.
- **Collaboration**: Public/Private toggle for sharing meeting links and insights.

---

## Technology Stack

### **Frontend & UI**
- **Streamlit**: For the high-performance, real-time web dashboard.
- **Tailored CSS**: Custom glassmorphic components and midnight-themed aesthetics.

### **AI & Machine Learning**
- **Transcription**: OpenAI Whisper (via `faster-whisper`) for ultra-fast, low-latency STT.
- **Reasoning**: Google Gemini 2.5 Flash (Primary) & Ollama / Qwen 2.5 (Local Fallback).
- **Diarization**: NVIDIA NeMo TitaNet-L for precise speaker identification.
- **Search**: RAG (Retrieval-Augmented Generation) with SQLite-based semantic indexing.

### **Backend & Automation**
- **Orchestration**: Python 3.11+.
- **Automation**: Playwright for autonomous browser navigation.
- **Audio Engine**: FFmpeg for high-quality audio routing and encoding.
- **Database**: SQLite for persistent meeting history and user settings.
- **Auth**: Google OAuth 2.0 for secure login and calendar access.

---

## Installation & Setup

### 1. Prerequisites
- **Python 3.10 - 3.12**
- **FFmpeg**: External system dependency for audio processing.
- **VB-CABLE Driver**: Required for bot audio capture on Windows.
- **Ollama**: (Optional for Local AI) Local machine learning server.

### 2. Clone & Initial Setup
```bash
git clone https://github.com/Chandisha/RENATA_Notes_AI.git
cd RENATA_Notes_AI
python -m venv rena
.\rena\Scripts\Activate.ps1  # Windows
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
playwright install chromium
```

### 4. Configure Environment & Security
For security, RENA never stores API keys in the code. You must use a `.env` file:
1. Copy the template: `cp .env.example .env`
2. Open `.env` and enter your actual credentials:
   - `GEMINI_API_KEY`: Your key from Google AI Studio.
   - `SMTP_PASS`: Your Gmail App Password (not your main password).
   - `TWILIO_AUTH_TOKEN`: From your Twilio console.
3. The `.env` file is already listed in `.gitignore` to prevent it from being uploaded.

---

## Usage Guide

### **Mode A: The Web Dashboard (Recommended)**
Start the central hub to manage meetings, view analytics, and use the AI Search Assistant:
```bash
streamlit run frontend.py
```

### **Mode B: The Autopilot Bot**
Dispatch the bot to a specific meeting URL:
```bash
python rena_bot_pilot.py "https://meet.google.com/xxx-xxxx-xxx"
```

### **Mode C: Manual Processor**
Process an existing audio file for AI analysis:
```bash
python meeting_notes_generator.py "path/to/audio.wav"
```

---

## Project Structure
```text
RENATA-meet/
├── components/            # UI components for the dashboard
├── fonts/                 # Devanagari fonts for Hindi PDF reports
├── meeting_outputs/       # Database, recordings, and generated reports
├── frontend.py            # Main Streamlit Dashboard
├── rena_bot_pilot.py      # Meeting Automation Bot
├── meeting_notes_generator.py # AI Inference Engine
├── meeting_database.py    # Backend History Management
├── search_copilot_service.py # AI Search Assistant
└── integrations_service.py # Gmail, Notion, & HubSpot integrations
```

---

## Future Prospects & Roadmap

- **Chrome & Gmail Extensions**: Direct "Join with RENA" buttons in Google Workspace.
- **Advanced Diarization**: Multi-modal speaker detection using video cues.
- **Slack/Discord Tunnels**: Push meeting summaries directly to project channels.
- **Real-time Translation**: Live translation of meeting audio for global teams.
- **Custom LLM Training**: Fine-tuned models for specific industry domains (Legal, Medical, Technical).

---

## Credits & Developer
Developing a future where conversations are never lost.

**Developer**: [Chandisha Das](https://github.com/Chandisha)  
**Version**: 1.0.0  
