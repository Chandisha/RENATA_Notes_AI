# RENATA - AI Meeting Intelligence Platform

**Live Application**: [meet.nexren.ai](https://meet.nexren.ai)

RENATA is an autonomous meeting intelligence platform that joins Google Meet and Zoom calls as a silent bot. It captures high-fidelity audio directly via browser-native technology and generates structured AI-powered reports — including transcripts, professional summaries, action items, and speaker analytics.

---

## 🚀 The Browser-Native Advantage

RENATA has moved beyond legacy virtual audio drivers. We have completely **removed** dependencies on VB-CABLE, VoiceMeeter, and FFmpeg for audio capture.

- ✅ **No Drivers Required**: Works out of the box with zero virtual audio installation.
- ✅ **Unlimited Isolated Slots**: Record multiple meetings simultaneously with perfect audio isolation.
- ✅ **Hinglish & Multilingual**: Powered by Gemini 3.0 Flash for superior transcription of mixed-language meetings.
- ✅ **Zero BIOS Changes**: Unlike driver-based solutions, RENATA works perfectly with Windows Secure Boot enabled.

---

## 🏛️ Architecture Overview

RENATA uses a "Brain (Cloud) and Body (Local)" architecture to provide a seamless web experience without the cost of high-compute cloud bots.

- **Vercel Dashboard**: Manage your reports, search your history (RAG), and track live bot status.
- **Local Pilot**: A lightweight Python process on your PC that launches Chromium to join and record meetings.
- **Gemini Engine**: All intelligence is processed via the Gemini 3.0 Flash API for industry-leading speed and accuracy.

---

## ✨ Features

- **Autonomous Join**: Automatically detects and joins meetings from your Google Calendar.
- **Intelligence Reports**: Generates professional summaries, MoM, and owner-assigned action items.
- **Intelligence Hub**: A clean, one-click interface in the Note Taking tab to access all analysis.
- **Global Search**: Find anything said in any meeting using natural language queries.
- **Privacy-First**: No live captions are scraped; audio is captured privately and processed at the end.

---

## 🛠️ Tech Stack

| Component | Technology |
|---|---|
| **Intelligence** | Google Gemini 3.0 Flash |
| **Automation** | Playwright Chromium (with Stealth) |
| **Audio Capture** | **Browser MediaRecorder (Native/Standard)** |
| **Backend** | FastAPI / Python 3.11 |
| **Database** | PostgreSQL (Neon) |
| **Frontend** | Vanilla JS / modern CSS |

---

## 🚀 Quick Start (Local Bot)

### 1. Prerequisites
- **Python 3.11**
- **Playwright**

### 2. Installation
```bash
git clone https://github.com/Chandisha/RENATA_Notes_AI.git
cd RENATA_Notes_AI

# Setup Environment
python -m venv venv
.\venv\Scripts\activate  # Windows
pip install -r requirements.txt
playwright install chromium
```

### 3. Environment Setup (.env)
Create a `.env` in your project root:
```env
GEMINI_API_KEY=your_key_here
DATABASE_URL=postgresql://your_neon_db_url
BOT_EMAIL=renata@nexren.ai
BOT_PASSWORD=your_pass
```

### 4. Run the Bot
```bash
python renata_bot_pilot.py
```

---

## 📂 Project Structure

- **`renata_bot_pilot.py`**: The "Body" — handles meeting joining and native audio capture.
- **`main.py`**: The "Brain" — handles the dashboard, web API, and user management.
- **`meeting_notes_generator.py`**: The processing engine that converts audio to intelligence.
- **`v3-frontend/`**: The modern dashboard UI.

---

## 🤝 Support

**Developer**: [Chandisha Das](https://github.com/Chandisha)

RENATA is an open-source alternative to commercial intelligence tools, focusing on data ownership and zero infrastructure costs.
