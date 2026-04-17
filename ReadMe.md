# MeetAI by Nexren - Enterprise Meeting Intelligence

**Live Application**: [meet.nexren.ai](https://meet.nexren.ai)

MeetAI is a production-grade meeting intelligence platform that joins Google Meet and Zoom calls as an autonomous agent. It utilizes browser-native technology to capture high-fidelity audio without virtual drivers and leverages Google's Gemini 1.5 Flash models to generate structured transcripts, professional summaries, and actionable insights.

---

## 🚀 Key Advantages

- **Zero-Driver Architecture**: Unlike legacy solutions, MeetAI requires no virtual audio cables (VB-CABLE/VoiceMeeter). It captures audio directly from the browser's WebRTC stream using a custom-injected hook.
- **Unified Intelligence Hub**: A single, powerful interface for every meeting that consolidates pre-meeting Gmail context with post-meeting AI notes and bullet points.
- **Hinglish & Multilingual Support**: Specifically optimized for mixed-language meetings, providing accurate Roman-script transliteration for Hindi alongside fluent English.
- **Multi-User Isolation**: Built-in multi-tenant security architecture ensuring every user's data remains private and isolated at the database level.

---

## ✨ Features

- **Autonomous Calendar Sync**: Automatically monitors your Google and Zoom calendars to join scheduled meetings.
- **Intelligence Hub**: One-click access to everything you need: pre-meeting brief (via Gmail) and post-meeting notes (via AI).
- **Executive Summaries**: High-level overviews including Minutes of Meeting (MoM) and owner-assigned action items.
- **AI Chat Assistant**: A RAG-powered assistant that lets you query your entire meeting history using natural language.
- **Professional PDF Reporting**: Automated generation and email delivery of polished PDF reports (Summary + Full Transcripts).
- **Engagement Analytics**: Visual tracking of meeting frequency, duration, and engagement scores.

---

## 🛠️ Tech Stack

| Component | Technology |
|---|---|
| **AI Intelligence** | Google Gemini 1.5 Flash |
| **Automation** | Playwright Chromium (with Stealth & RTC Hook) |
| **Backend** | FastAPI / Python |
| **Database** | PostgreSQL (Production) / SQLite (Local) |
| **Frontend** | Vanilla JavaScript / Modern CSS (Outfit Typography) |
| **Payments** | Razorpay Integration |

---

## 🚀 Getting Started

### 1. Installation
```bash
git clone https://github.com/Chandisha/RENATA_Notes_AI.git
cd RENATA_Notes_AI

# Setup Environment
python -m venv venv
source venv/bin/activate  # 或 .\venv\Scripts\activate on Windows
pip install -r requirements.txt
playwright install chromium
```

### 2. Configuration (.env)
Create a `.env` in the project root with the following keys:
- `GEMINI_API_KEY`: Your Google AI Studio key.
- `BOT_EMAIL` / `BOT_PASSWORD`: Dedicated Google account for the bot.
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`: For user OAuth integration.
- `SMTP_SENDER_EMAIL` / `BOT_SMTP_PASSWORD`: For automated email reports.

### 3. Execution
```bash
# Start the Backend Server
uvicorn main:app --reload

# Start the Bot Pilot (on the recording machine)
python renata_bot_pilot.py
```

---

## 📂 Project Core Structure

- **`main.py`**: Central API server handling sessions, OAuth, and the SPA dashboard.
- **`renata_bot_pilot.py`**: The meeting agent — handles joining, capture, and lobby management.
- **`meeting_notes_generator.py`**: The AI engine — uploads audio to Gemini and builds PDF reports.
- **`v3-frontend/`**: The modern Single Page Application interface.
- **`meeting_database.py`**: Universal database layer for multi-user isolation.

---

## 🤝 Support & Development

**Maintained by**: [Chandisha Das](https://github.com/Chandisha)
**Powered by**: [Nexren](https://nexren.ai)

MeetAI is designed for data ownership and zero-infrastructure overhead, providing a professional alternative to enterprise recording twins.
