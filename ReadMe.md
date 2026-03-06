# RENATA - AI Meeting Intelligence Platform

**Live Application**: https://renata-notes-ai.vercel.app

RENATA is an autonomous meeting intelligence platform. It joins your Google Meet and Zoom calls as a silent bot, records the audio, and generates structured AI-powered reports — transcripts, summaries, action items, speaker analytics, and a searchable knowledge base — all from a cloud dashboard.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Features](#features)
3. [Tech Stack](#tech-stack)
4. [Prerequisites](#prerequisites)
5. [Local Development Setup](#local-development-setup)
6. [Cloud Deployment on Vercel](#cloud-deployment-on-vercel)
7. [The Hybrid Setup: Cloud Dashboard and Local Bot](#the-hybrid-setup)
8. [Project Structure](#project-structure)
9. [Environment Variables Reference](#environment-variables-reference)
10. [Usage Guide](#usage-guide)
11. [Developer](#developer)

---

## Architecture Overview

RENATA uses a split "Brain and Body" architecture to provide cloud-delivered features without expensive cloud compute for browser automation.

```
+------------------------+        +-----------------------------+
|   Vercel (The Brain)   |        |  Your Computer (The Body)   |
|                        |  HTTP  |                             |
|  - Web Dashboard       <--------+  - renata_bot_pilot.py      |
|  - FastAPI API          |        |  - Playwright Chrome Bot    |
|  - AI Search (RAG)     |        |  - Audio Recording          |
|  - User Accounts       |        |  - PDF Generation           |
|  - PostgreSQL (Neon)   |        |  - Local Transcription      |
+------------------------+        +-----------------------------+
```

- The **Vercel app** (the Brain) handles the web UI and stores all data in a cloud PostgreSQL database.
- The **local pilot** (the Body) polls the cloud database for dispatched meetings, then uses Playwright to open a real Chrome browser and join the call.
- Results (transcripts, PDFs, summaries) are written back to the shared database and appear in the dashboard.

---

## Features

### Autonomous Meeting Bot
- Automatically joins meetings from your Google Calendar at the scheduled start time.
- Supports Google Meet and Zoom via Playwright browser automation.
- Joins silently with camera off and microphone muted.
- Leaves automatically when the meeting ends or the room stays empty.

### AI Processing Pipeline
- **Transcription** using Google Gemini 3 Flash (fallback to Gemini 2.5 Flash).
- **Speaker Diarization** to attribute speech to individual participants.
- **Meeting Intelligence** including summaries, minutes of meeting, and action items.
- **PDF Report Generation** with full UTF-8 support.

### Live Status Tracking
- Real-time bot status displayed on the dashboard as the bot moves through stages: Dispatching, Fetching, Connecting, In Lobby, Live In Call.

### AI Search Assistant (RAG)
- All meeting transcripts and generated PDFs are indexed into a ChromaDB vector store.
- Ask natural language questions like "What were the action items from last Monday?" and get precise, citation-backed answers powered by Gemini.
- Sync Knowledge Base button to re-index your archive at any time.

### User Accounts and Settings
- Google Sign-In for authentication (OAuth 2.0).
- Editable display name. Gmail address is shown read-only.
- Bot preferences: display name, auto-join toggle, recording toggle.
- Account deletion with full data wipe.

### Dashboard and Analytics
- Meeting statistics: total meetings, hours captured, action items, participants.
- Upcoming meetings from Google Calendar.
- Recent AI reports list with PDF download links.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend Framework | FastAPI |
| Authentication | Google OAuth 2.0 |
| LLM / AI | Google Gemini 3 Flash (primary), Gemini 2.5 Flash (fallback) |
| Vector Database | ChromaDB |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) |
| Meeting Bot | Playwright with Chromium |
| Cloud Database | PostgreSQL via Neon.tech |
| Local Database | SQLite (for local-only development) |
| PDF Generation | ReportLab |
| Frontend | Vanilla HTML, CSS, JavaScript |
| Deployment | Vercel (Serverless Python) |
| Calendar / Gmail | Google Calendar API, Gmail API |
| Zoom Integration | Zoom OAuth API |

---

## Prerequisites

Before starting, make sure you have the following installed on your computer.

- **Python 3.10 to 3.12** (Python 3.11 recommended)
- **Git**
- **FFmpeg** for audio processing
  - Windows: Download from https://ffmpeg.org/download.html and add to your PATH
- **VB-CABLE** for virtual audio routing (required for bot audio capture on Windows)
  - Download from https://vb-audio.com/Cable/

---

## Local Development Setup

### Step 1: Clone the Repository

```
git clone https://github.com/Chandisha/RENATA_Notes_AI.git
cd RENATA_Notes_AI
```

### Step 2: Create a Python Virtual Environment

It is strongly recommended to use a virtual environment to avoid dependency conflicts.

```
python -m venv renata
```

Activate the environment:
- Windows: `.\renata\Scripts\activate`
- Linux / macOS: `source renata/bin/activate`

You should see `(renata)` appear in your terminal prompt.

### Step 3: Install Dependencies

```
pip install -r requirements.txt
playwright install chromium
```

This will install all required packages including FastAPI, Playwright, ChromaDB, sentence-transformers, and the Google AI libraries.

### Step 4: Set Up Google OAuth Credentials

RENATA requires a Google Cloud project to enable Sign-In with Google and access Calendar and Gmail.

1. Go to https://console.cloud.google.com
2. Create a new project.
3. Enable the following APIs for your project:
   - Google Calendar API
   - Gmail API
   - People API
4. Go to APIs and Services > Credentials.
5. Click Create Credentials > OAuth 2.0 Client ID.
6. Select Web Application as the type.
7. Add the following as an Authorized Redirect URI:
   - `http://127.0.0.1:8000/auth/callback` (for local development)
   - `https://your-app.vercel.app/auth/callback` (for production)
8. Click Create, then download the JSON file.
9. Rename the downloaded file to `credentials.json` and place it in the root of the project folder.

### Step 5: Create the Environment File

Create a file named `.env` in the root of the project with the following contents:

```
GEMINI_API_KEY=your_gemini_api_key_here
SESSION_SECRET=any_long_random_string_here

# Zoom OAuth (optional, only if you want Zoom integration)
ZOOM_CLIENT_ID=your_zoom_client_id
ZOOM_CLIENT_SECRET=your_zoom_client_secret

# Leave this blank for local SQLite, or add your Neon URL for local PostgreSQL
# DATABASE_URL=postgresql://...
```

To get a Gemini API key, visit https://aistudio.google.com/app/apikey.

### Step 6: Start the Local Web Server

```
uvicorn main:app --reload --port 8000
```

Open your browser and go to http://127.0.0.1:8000 to access the dashboard locally.

---

## Cloud Deployment on Vercel

### Step 1: Set Up a PostgreSQL Database (Neon)

Vercel's filesystem is temporary and resets on each deployment. You must use a cloud database.

1. Go to https://neon.tech and create a free account.
2. Create a new project.
3. From your Neon dashboard, copy the connection string. It looks like:
   ```
   postgresql://neondb_owner:YOUR_PASSWORD@ep-something.aws.neon.tech/neondb?sslmode=require
   ```
4. Set this as your `DATABASE_URL` in Step 3 below.
5. Initialize the database tables by running this once locally with the `DATABASE_URL` set in your `.env`:
   ```
   python init_pg_db.py
   ```

### Step 2: Connect Repository to Vercel

1. Go to https://vercel.com and sign in.
2. Click Add New > Project.
3. Import your GitHub repository `RENATA_Notes_AI`.
4. Vercel will auto-detect the `vercel.json` configuration.

### Step 3: Add Environment Variables in Vercel

In your Vercel project settings, go to Settings > Environment Variables and add the following:

| Variable Name | Description |
|---|---|
| `DATABASE_URL` | Your Neon PostgreSQL connection string |
| `GEMINI_API_KEY` | Your Google Gemini API key |
| `GOOGLE_CREDENTIALS_JSON` | Paste the entire contents of your `credentials.json` file here |
| `SESSION_SECRET` | Any long random string for session encryption |
| `ZOOM_CLIENT_ID` | Your Zoom OAuth App Client ID (optional) |
| `ZOOM_CLIENT_SECRET` | Your Zoom OAuth App Client Secret (optional) |

### Step 4: Update Google OAuth Redirect URI

In Google Cloud Console, go to your OAuth 2.0 Client ID and add your Vercel URL as an Authorized Redirect URI:

```
https://your-app-name.vercel.app/auth/callback
```

### Step 5: Deploy

Push any change to the `main` branch of your GitHub repository. Vercel will automatically build and deploy your application.

---

## The Hybrid Setup

Once your Vercel app is live, you need to run the local bot pilot on your computer to actually join meetings. This is a one-time setup per session.

### Why is the local pilot needed?

Vercel functions have a maximum execution time of 30 to 60 seconds. Joining and staying in a meeting for 60 minutes, recording audio, and running browser automation requires a persistent process, which Vercel cannot provide. The local pilot fills this role.

### Running the Local Bot Pilot

Each time you want RENATA to be able to join meetings, do the following:

1. Open a terminal and navigate to the project folder.
2. Activate the virtual environment:
   ```
   .\renata\Scripts\activate
   ```
3. Ensure your `.env` file contains the real `DATABASE_URL` from Neon (the same one used by Vercel).
4. Start the pilot:
   ```
   python renata_bot_pilot.py
   ```

The pilot will automatically:
- Detect your user account from the shared database.
- Start listening in autopilot mode.
- Poll the database every 30 seconds for new meetings to join.
- Join meetings from your Google Calendar when they are about to start.
- Pick up manual dispatch requests from the Live Control Room on the dashboard.

### Automating the Pilot on Windows

To avoid running the command manually every day, create a file named `start_renata.bat` on your Desktop with the following content:

```
@echo off
cd /d D:\RENATA-meet
call .\renata\Scripts\activate
python renata_bot_pilot.py
pause
```

Double-click this file each morning to start the bot in one step.

---

## Project Structure

```
RENATA_Notes_AI/
|
|-- main.py                     Main FastAPI application, all API routes and OAuth handlers
|-- renata_bot_pilot.py         Local bot that joins meetings using Playwright
|-- meeting_database.py         Database layer supporting both SQLite and PostgreSQL
|-- meeting_notes_generator.py  Gemini AI pipeline for transcription and report generation
|-- init_pg_db.py               One-time script to initialize PostgreSQL tables on Neon
|-- refresh_token.py            One-time script to re-authenticate locally if token expires
|
|-- rag/
|   |-- llm_manager.py          Manages Gemini model selection and fallback logic
|   |-- rag_chatbot.py          ChromaDB vector store and retrieval logic
|
|-- v3-frontend/
|   |-- index.html              Single Page Application shell
|   |-- app.js                  All frontend JavaScript logic
|   |-- styles.css              All CSS styles
|
|-- api/
|   |-- requirements.txt        Python dependencies for Vercel deployment
|
|-- vercel.json                 Vercel build and routing configuration
|-- requirements.txt            Python dependencies for local development
|-- credentials.json            Google OAuth client secrets (not committed to Git)
|-- .env                        Local environment variables (not committed to Git)
|-- meeting_outputs/            Local folder where recordings and PDFs are saved
```

---

## Environment Variables Reference

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | Yes | Google Gemini API key from aistudio.google.com |
| `SESSION_SECRET` | Yes | A long random string used to sign session cookies |
| `DATABASE_URL` | Yes (Vercel) | PostgreSQL connection string from Neon or similar |
| `GOOGLE_CREDENTIALS_JSON` | Yes (Vercel) | Full JSON content of your credentials.json file |
| `ZOOM_CLIENT_ID` | No | Zoom OAuth App Client ID for Zoom integration |
| `ZOOM_CLIENT_SECRET` | No | Zoom OAuth App Client Secret for Zoom integration |

---

## Usage Guide

### Logging In

1. Open the application URL in your browser.
2. Click Sign In with Google.
3. Authorize RENATA to access your Google Calendar and Gmail.

### Manual Dispatch (Join a Specific Meeting)

1. Go to the Live Control Room tab in the sidebar.
2. Paste a Google Meet or Zoom URL into the input field.
3. Click Dispatch Renata.
4. The Bot Status card will update in real time as the bot goes through Dispatching, Fetching, Connecting, In Lobby, and Live stages.

Note: The local bot pilot must be running on your computer for the bot to actually join the meeting.

### Auto-Join from Calendar

When the local pilot is running, it scans your Google Calendar every 30 seconds. If an event is starting within the next 5 minutes and has a Google Meet or Zoom link, the bot will join automatically.

### Viewing Reports

1. Go to the Reports tab to see a list of all completed meetings.
2. Click PDF to download the full AI-generated meeting report.

### AI Search (Knowledge Base)

1. Go to the AI Search tab.
2. Type a question in natural language, for example: "What decisions were made about the product launch?"
3. RENATA will search your indexed meeting transcripts and return a precise answer.
4. Click Sync Knowledge Base to re-index if you have added new meetings recently.

### Settings

1. Go to the Settings tab.
2. You can update your display name (your Gmail address is shown read-only and cannot be changed).
3. Configure bot preferences including the bot's display name, auto-join behavior, and recording options.
4. Use the Danger Zone section to permanently delete your account and all associated data.

---

## Developer

**Chandisha Das**
GitHub: https://github.com/Chandisha

RENATA is an open-source self-hosted meeting intelligence platform designed as a free alternative to commercial tools like Read.ai and Otter.ai.
