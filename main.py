"""
RENATA - Enterprise Meeting Intelligence System
FastAPI Production Backend
Replaces: streamlit run frontend.py
Run with: uvicorn main:app --reload
"""
import os
import json
import subprocess
import sys
import requests
import base64
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import meeting_database as db
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
import googleapiclient.discovery

# --- Zoom OAuth Constants ---
ZOOM_CLIENT_ID = os.getenv("ZOOM_CLIENT_ID")
ZOOM_CLIENT_SECRET = os.getenv("ZOOM_CLIENT_SECRET")
ZOOM_AUTH_URL = "https://zoom.us/oauth/authorize"
ZOOM_TOKEN_URL = "https://zoom.us/oauth/token"

# --- App Setup ---
app = FastAPI(title="RENATA Meeting Intelligence", version="1.0.0")

# Session middleware (secret key from env for production)
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", "renata-local-dev-secret-2024"))

# Static files & templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Init database on startup
db.init_database()

# --- Jinja2 Global Helpers ---
def get_meeting_status(start_time: str, end_time: str = None):
    try:
        now = datetime.now(timezone.utc)
        start = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        if end_time:
            end = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
            if now > end:
                return ("COMPLETED", "#10b981", "")
        diff = (start - now).total_seconds() / 60
        if diff < -5:   return ("IN PROGRESS", "#10b981", "")
        elif diff < 0:  return ("JUST STARTED", "#f59e0b", "")
        elif diff < 5:  return ("STARTING SOON", "#f59e0b", "")
        elif diff < 60: return ("UPCOMING", "#3b82f6", "")
        else:           return ("SCHEDULED", "#6b7280", "")
    except:
        return ("UNKNOWN", "#6b7280", "")

def fmt_time(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        return dt.strftime("%b %d, %Y  %I:%M %p")
    except:
        return iso_str or "—"

templates.env.globals["get_meeting_status"] = get_meeting_status
templates.env.globals["fmt_time"] = fmt_time
templates.env.globals["now_year"] = datetime.now().year

# --- Google OAuth Helper ---
def get_user_credentials(user_email: str):
    """Fetch and refresh user credentials from DB."""
    serialized = db.get_user_token(user_email)
    if not serialized:
        return None
        
    creds = Credentials.from_authorized_user_info(json.loads(serialized), GOOGLE_SCOPES)
    if creds and creds.expired and creds.refresh_token:
        try:
            from google.auth.transport.requests import Request as GoogleRequest
            creds.refresh(GoogleRequest())
            # Update DB with refreshed token
            conn = db.get_db_connection()
            conn.execute("UPDATE users SET google_token = ?, updated_at = CURRENT_TIMESTAMP WHERE email = ?",
                         (creds.to_json(), user_email))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Token refresh error for {user_email}: {e}")
            return None
    return creds

# --- Google OAuth Scopes ---
GOOGLE_SCOPES = [
    'openid',
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/drive.metadata.readonly'
]

# --- Auth Helper ---
def get_current_user(request: Request):
    """Get logged-in user from session."""
    return request.session.get("user")

def require_user(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    return user

# ============================================================
# AUTH ROUTES
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse("/dashboard")
    return RedirectResponse("/login")

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse("/dashboard")
    error = request.query_params.get("error")
    return templates.TemplateResponse("login.html", {"request": request, "error": error})

@app.get("/auth/google")
async def trigger_google_auth(request: Request):
    """Initiate Google OAuth flow (Multi-User)"""
    if not os.path.exists('credentials.json'):
        return RedirectResponse("/login?error=credentials_missing")
        
    flow = Flow.from_client_secrets_file(
        'credentials.json',
        scopes=GOOGLE_SCOPES,
        redirect_uri=f"{request.url.scheme}://{request.url.netloc}/auth/callback"
    )
    
    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline', include_granted_scopes='true')
    return RedirectResponse(auth_url)

@app.get("/auth/zoom")
async def trigger_zoom_auth(request: Request):
    """Initiate Zoom OAuth flow"""
    if not ZOOM_CLIENT_ID or not ZOOM_CLIENT_SECRET:
        return RedirectResponse("/integrations?error=zoom_keys_missing")
        
    redirect_uri = f"{request.url.scheme}://{request.url.netloc}/auth/zoom/callback"
    auth_url = f"{ZOOM_AUTH_URL}?response_type=code&client_id={ZOOM_CLIENT_ID}&redirect_uri={redirect_uri}"
    return RedirectResponse(auth_url)

@app.get("/auth/zoom/callback")
async def zoom_callback(request: Request, code: str):
    """Handle Zoom OAuth callback"""
    user = require_user(request)
    redirect_uri = f"{request.url.scheme}://{request.url.netloc}/auth/zoom/callback"
    
    # Exchange code for token
    auth_header = base64.b64encode(f"{ZOOM_CLIENT_ID}:{ZOOM_CLIENT_SECRET}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth_header}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri
    }
    
    response = requests.post(ZOOM_TOKEN_URL, headers=headers, data=data)
    if response.status_code != 200:
        return RedirectResponse(f"/integrations?error=zoom_auth_failed&details={response.text}")
        
    token_data = response.json()
    
    # Save Zoom token to DB
    conn = db.get_db_connection()
    conn.execute("UPDATE users SET zoom_token = ?, updated_at = CURRENT_TIMESTAMP WHERE email = ?",
                 (json.dumps(token_data), user['email']))
    conn.commit()
    conn.close()
    
    return RedirectResponse("/integrations?msg=Zoom+connected+successfully")

@app.get("/auth/callback")
async def google_callback(request: Request):
    """Handle Google OAuth response, create/update user profile and store token"""
    if "error" in request.query_params:
        return RedirectResponse(f"/login?error={request.query_params['error']}")
        
    code = request.query_params.get("code")
    if not code:
        return RedirectResponse("/login?error=no_code")

    try:
        flow = Flow.from_client_secrets_file(
            'credentials.json',
            scopes=GOOGLE_SCOPES,
            redirect_uri=f"{request.url.scheme}://{request.url.netloc}/auth/callback"
        )
        flow.fetch_token(code=code)
        creds = flow.credentials

        # Get User Info from Google
        from googleapiclient.discovery import build
        user_info_service = build('oauth2', 'v2', credentials=creds)
        user_info = user_info_service.userinfo().get().execute()

        email = user_info.get("email")
        name = user_info.get("name")
        picture = user_info.get("picture")

        # Save/Update in Database
        conn = db.get_db_connection()
        cursor = conn.cursor()
        
        # Check if user exists
        cursor.execute("SELECT email FROM users WHERE email = ?", (email,))
        if cursor.fetchone():
            cursor.execute("""
                UPDATE users SET 
                    name = ?, 
                    picture = ?, 
                    google_token = ?, 
                    updated_at = CURRENT_TIMESTAMP 
                WHERE email = ?
            """, (name, picture, creds.to_json(), email))
        else:
            cursor.execute("""
                INSERT INTO users (email, name, picture, google_token) 
                VALUES (?, ?, ?, ?)
            """, (email, name, picture, creds.to_json()))
        
        conn.commit()
        conn.close()

        # Set Session
        request.session["user"] = {
            "email": email,
            "name": name,
            "picture": picture
        }
        
        return RedirectResponse("/dashboard")
        
    except Exception as e:
        print(f"Auth Callback Error: {e}")
        return RedirectResponse(f"/login?error=auth_failed&details={str(e)}")

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    if os.path.exists("token.json"):
        try: os.remove("token.json")
        except: pass
    return RedirectResponse("/login", status_code=303)

# ============================================================
# DASHBOARD / CALENDAR
# ============================================================

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    user = require_user(request)
    email = user['email']

    # Fetch Google Calendar events for the specific user
    calendar_events = []
    error_msg = None
    try:
        creds = get_user_credentials(email)
        if creds:
            from googleapiclient.discovery import build
            svc = build("calendar", "v3", credentials=creds)
            now_iso = datetime.utcnow().isoformat() + "Z"
            result = svc.events().list(
                calendarId="primary", timeMin=now_iso,
                maxResults=15, singleEvents=True, orderBy="startTime"
            ).execute()
            calendar_events = result.get("items", [])
        else:
            error_msg = "Google Calendar not connected. Please login again."
    except Exception as e:
        error_msg = str(e)

    stats = db.get_meeting_stats(user_email=email)
    recent = db.get_all_meetings(user_email=email, limit=5)

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "events": calendar_events,
        "stats": stats,
        "recent_meetings": recent,
        "error": error_msg,
        "active_page": "calendar"
    })

# ============================================================
# REPORTS / HISTORY
# ============================================================

@app.get("/reports", response_class=HTMLResponse)
async def reports(request: Request):
    user = require_user(request)
    meetings = db.get_all_meetings(user_email=user['email'], limit=50)
    return templates.TemplateResponse("reports.html", {
        "request": request,
        "user": user,
        "meetings": meetings,
        "active_page": "reports"
    })

@app.get("/reports/{meeting_id}", response_class=HTMLResponse)
async def report_detail(request: Request, meeting_id: str):
    user = get_current_user(request)
    if not user: return RedirectResponse("/login")
    meeting = db.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    # Parse JSON fields
    for field in ["action_items", "participant_emails", "chapters"]:
        if meeting.get(field) and isinstance(meeting[field], str):
            try: meeting[field] = json.loads(meeting[field])
            except: pass
    return templates.TemplateResponse("report_detail.html", {
        "request": request,
        "user": user,
        "meeting": meeting,
        "active_page": "reports"
    })

# ============================================================
# ANALYTICS
# ============================================================

@app.get("/analytics", response_class=HTMLResponse)
async def analytics(request: Request):
    user = require_user(request)
    stats = db.get_meeting_stats(user_email=user['email'])
    # Parse speaker_distribution
    speaker_dist = stats.get("speaker_distribution", {})
    return templates.TemplateResponse("analytics.html", {
        "request": request,
        "user": user,
        "stats": stats,
        "speaker_json": json.dumps(speaker_dist),
        "active_page": "analytics"
    })

# ============================================================
# AI SEARCH ASSISTANT (RAG)
# ============================================================

@app.get("/search", response_class=HTMLResponse)
async def search_page(request: Request):
    user = require_user(request)

    # Get knowledge base stats for the UI
    kb_stats = _get_kb_stats()

    return templates.TemplateResponse("search.html", {
        "request": request,
        "user": user,
        "active_page": "search",
        "kb_stats": kb_stats
    })

def _get_kb_stats():
    """Get knowledge base file and index stats."""
    meeting_dir = Path("meeting_outputs")
    stats = {"pdf_count": 0, "json_count": 0, "indexed_segments": 0, "status": "unknown"}
    if meeting_dir.exists():
        stats["pdf_count"] = len(list(meeting_dir.glob("*.pdf")))
        stats["json_count"] = len(list(meeting_dir.glob("*.json")))
    try:
        from rag_assistant import assistant
        if assistant.chatbot.is_initialized and assistant.chatbot.vector_store:
            stats["indexed_segments"] = assistant.chatbot.vector_store.get_document_count()
            stats["status"] = "ready"
        else:
            stats["status"] = "not_initialized"
    except:
        stats["status"] = "not_initialized"
    return stats

@app.post("/search/ask", response_class=JSONResponse)
async def search_ask(request: Request, question: str = Form(...)):
    user = get_current_user(request)
    if not user: raise HTTPException(status_code=401)
    try:
        from rag_assistant import assistant
        answer = assistant.ask(question)
        return {"answer": answer, "success": True}
    except Exception as e:
        return {"answer": f"Error: {str(e)}", "success": False}

@app.post("/search/index", response_class=JSONResponse)
async def search_index(request: Request):
    """Force re-index all meeting documents into the RAG knowledge base."""
    user = get_current_user(request)
    if not user: raise HTTPException(status_code=401)
    try:
        from rag_assistant import assistant
        assistant._ensure_indexed(force_reset=True)
        count = assistant.chatbot.vector_store.get_document_count()
        return {"success": True, "message": f"Knowledge base synced. {count} segments indexed.", "indexed_segments": count}
    except Exception as e:
        return {"success": False, "message": f"Indexing error: {str(e)}"}

@app.get("/search/status", response_class=JSONResponse)
async def search_status(request: Request):
    """Return current knowledge base stats."""
    user = get_current_user(request)
    if not user: raise HTTPException(status_code=401)
    return _get_kb_stats()

# ============================================================
# INTEGRATIONS
# ============================================================

@app.get("/integrations", response_class=HTMLResponse)
async def integrations_page(request: Request):
    user = require_user(request)
    profile = db.get_user_profile(user["email"]) or {}
    return templates.TemplateResponse("integrations.html", {
        "request": request,
        "user": user,
        "profile": profile,
        "active_page": "integrations"
    })

# ============================================================
# ADD LIVE MEETING
# ============================================================

@app.get("/live", response_class=HTMLResponse)
async def live_page(request: Request):
    user = require_user(request)
    return templates.TemplateResponse("live.html", {
        "request": request, "user": user, "active_page": "live"
    })

@app.post("/live/join", response_class=JSONResponse)
async def live_join(request: Request, meeting_url: str = Form(...)):
    user = require_user(request)
    try:
        # Pass the user email to the bot subprocess
        proc = subprocess.Popen([sys.executable, "renata_bot_pilot.py", meeting_url, "--user", user['email']])
        return {"success": True, "message": f"Renata is joining {meeting_url} for {user['email']}..."}
    except Exception as e:
        return {"success": False, "message": str(e)}

# ============================================================
# SETTINGS / PROFILE
# ============================================================

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    user = require_user(request)
    profile = db.get_user_profile(user["email"]) or {}
    return templates.TemplateResponse("settings.html", {
        "request": request, "user": user, "profile": profile, "active_page": "settings"
    })

@app.post("/settings/save")
async def settings_save(request: Request, name: str = Form(""), bot_name: str = Form("")):
    user = require_user(request)
    db.update_user_profile(user["email"], {"name": name, "bot_name": bot_name})
    # Update session name
    request.session["user"]["name"] = name
    return RedirectResponse("/settings?msg=Saved+successfully", status_code=303)

# ============================================================
# FILE DOWNLOADS
# ============================================================

@app.get("/download/pdf/{filename}")
async def download_pdf(filename: str, request: Request):
    user = get_current_user(request)
    if not user: raise HTTPException(status_code=401)
    path = Path("meeting_outputs") / filename
    if not path.exists(): raise HTTPException(status_code=404)
    return FileResponse(path, media_type="application/pdf", filename=filename)

@app.get("/download/json/{filename}")
async def download_json(filename: str, request: Request):
    user = get_current_user(request)
    if not user: raise HTTPException(status_code=401)
    path = Path("meeting_outputs") / filename
    if not path.exists(): raise HTTPException(status_code=404)
    return FileResponse(path, media_type="application/json", filename=filename)

# ============================================================
# HEALTH CHECK (Railway uses this)
# ============================================================

@app.get("/health")
async def health():
    return {"status": "ok", "service": "RENATA Meeting Intelligence"}
