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
import time
from pathlib import Path
from starlette.middleware.sessions import SessionMiddleware
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import meeting_database as db
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
import googleapiclient.discovery

# --- Zoom OAuth Constants ---
ZOOM_CLIENT_ID = os.getenv("ZOOM_CLIENT_ID")
ZOOM_CLIENT_SECRET = os.getenv("ZOOM_CLIENT_SECRET")
ZOOM_AUTH_URL = "https://zoom.us/oauth/authorize"
ZOOM_TOKEN_URL = "https://zoom.us/oauth/token"

from fastapi.middleware.cors import CORSMiddleware

# --- Lifespan for Vercel & Production ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # This runs when the server starts
    print(">>> SERVER STARTING: INITIALIZING DATABASE...")
    try:
        db.init_database()
        print(">>> DATABASE INITIALIZED SUCCESSFULLY.")
    except Exception as e:
        print(f"CRITICAL: Database Init Failed: {e}")
    yield

# --- App Setup ---
BASE_DIR = Path(__file__).resolve().parent
app = FastAPI(title="RENATA Meeting Intelligence", version="1.0.0", lifespan=lifespan)

# CORS Setup - Essential for Vercel Frontend
app.add_middleware(
    CORSMiddleware,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Session middleware (secret key from env for production)
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", "renata-local-dev-secret-2024"))

# Static files & templates

# Static files & templates
if (BASE_DIR / "static").exists():
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
else:
    print("WARNING: Static directory not found!")

if (BASE_DIR / "templates").exists():
    templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
else:
    print("WARNING: Templates directory not found!")
    # Fallback to avoid crash during startup
    templates = None

# Custom Exception Handler for 500s
@app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as e:
        import traceback
        print(f"RUNTIME ERROR: {e}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal Server Error", "error": str(e), "traceback": traceback.format_exc()}
        )


@app.get("/health")
def health_check():
    return {"status": "ok", "time": datetime.now().isoformat(), "env": os.getenv("VERCEL_ENV", "local")}

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

if templates:
    templates.env.filters["basename"] = lambda p: os.path.basename(p) if p else ""
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
            db.exec_commit("UPDATE users SET google_token = ?, updated_at = CURRENT_TIMESTAMP WHERE email = ?",
                          (creds.to_json(), user_email))
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
        # If no session, try to find the "main" user in the DB (since this is a private server)
        row = db.fetch_one("SELECT email, name, picture FROM users LIMIT 1")
        if row:
            return {"email": row["email"], "name": row["name"], "picture": row["picture"]}
        return {"email": "default@rena.ai", "name": "Local User"}
    return user

# --- Google OAuth Flow Helper ---
def create_google_flow(request: Request):
    """Create a Flow object from credentials.json or GOOGLE_CREDENTIALS_JSON env var."""
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    
    # FORCE the production URL as the callback for stability on Vercel
    if os.getenv("VERCEL_ENV"):
        redirect_uri = "https://renata-notes-ai.vercel.app/auth/callback"
    else:
        redirect_uri = f"{request.url.scheme}://{request.url.netloc}/auth/callback"
    
    print(f">>> USING REDIRECT URI: {redirect_uri}")
    
    if creds_json:
        # Load from JSON string in environment variable
        creds_info = json.loads(creds_json)
        return Flow.from_client_config(
            creds_info,
            scopes=GOOGLE_SCOPES,
            redirect_uri=redirect_uri
        )
    elif os.path.exists('credentials.json'):
        # Fallback to local file
        return Flow.from_client_secrets_file(
            'credentials.json',
            scopes=GOOGLE_SCOPES,
            redirect_uri=redirect_uri
        )
    return None

# ============================================================
# AUTH ROUTES
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    # FORCE Production Domain to avoid session loss on Previews
    host = request.headers.get("host", "")
    if "vercel.app" in host and host != "renata-notes-ai.vercel.app" and not host.startswith("localhost"):
        return RedirectResponse("https://renata-notes-ai.vercel.app/")

    print(">>> ACCESSING ROOT /")
    user = get_current_user(request)
    if user:
        return RedirectResponse("/dashboard")
    return RedirectResponse("/login")

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login")

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    # FORCE Production Domain
    host = request.headers.get("host", "")
    if "vercel.app" in host and host != "renata-notes-ai.vercel.app" and not host.startswith("localhost"):
        return RedirectResponse("https://renata-notes-ai.vercel.app/login")

    print(">>> ACCESSING LOGIN PAGE")
    user = get_current_user(request)
    if user:
        return RedirectResponse("/dashboard")
    error = request.query_params.get("error")
    return templates.TemplateResponse("login.html", {"request": request, "error": error})

@app.get("/auth/google")
async def trigger_google_auth(request: Request):
    """Initiate Google OAuth flow (Multi-User)"""
    flow = create_google_flow(request)
    if not flow:
        return RedirectResponse("/login?error=credentials_missing")
    
    auth_url, state = flow.authorization_url(prompt='consent', access_type='offline', include_granted_scopes='true')
    
    # Store the state and code verifier in the session for the callback
    request.session["oauth_state"] = state
    if hasattr(flow, "code_verifier"):
        request.session["code_verifier"] = flow.code_verifier
        
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
    db.exec_commit("UPDATE users SET zoom_token = ?, updated_at = CURRENT_TIMESTAMP WHERE email = ?",
                  (json.dumps(token_data), user['email']))
    
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
        flow = create_google_flow(request)
        if not flow:
            return RedirectResponse("/login?error=credentials_missing")
            
        # Restore the code verifier from the session
        code_verifier = request.session.get("code_verifier")
        flow.fetch_token(code=code, code_verifier=code_verifier)
        
        creds = flow.credentials

        # Get User Info from Google
        from googleapiclient.discovery import build
        user_info_service = build('oauth2', 'v2', credentials=creds)
        user_info = user_info_service.userinfo().get().execute()

        email = user_info.get("email")
        name = user_info.get("name")
        picture = user_info.get("picture")

        # Save/Update in Database
        # Check if user exists
        existing_user = db.fetch_one("SELECT email FROM users WHERE email = ?", (email,))
        if existing_user:
            db.exec_commit("""
                UPDATE users SET 
                    name = ?, 
                    picture = ?, 
                    google_token = ?, 
                    updated_at = CURRENT_TIMESTAMP 
                WHERE email = ?
            """, (name, picture, creds.to_json(), email))
        else:
            db.exec_commit("""
                INSERT INTO users (email, name, picture, google_token) 
                VALUES (?, ?, ?, ?)
            """, (email, name, picture, creds.to_json()))
        
        # Set Session
        request.session["user"] = {
            "email": email,
            "name": name,
            "picture": picture
        }
        
        # If the origin was Vercel, redirect back there
        return RedirectResponse("/#dashboard")
        
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
async def dashboard_page_spa(request: Request):
    """Serve the SPA shell for the dashboard."""
    require_user(request)
    return FileResponse(os.path.join(BASE_DIR, "v3-frontend", "index.html"))

@app.get("/dashboard_data")
async def dashboard_data(request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized", "redirect": "/login"}, status_code=401)
    
    email = user['email']
    calendar_events = []
    try:
        creds = get_user_credentials(email)
        if creds:
            from googleapiclient.discovery import build
            svc = build("calendar", "v3", credentials=creds)
            # RFC3339 compliant format
            now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            result = svc.events().list(
                calendarId="primary", timeMin=now_iso,
                maxResults=10, singleEvents=True, orderBy="startTime"
            ).execute()
            items = result.get("items", [])
            for item in items:
                start_raw = item['start'].get('dateTime', item['start'].get('date'))
                calendar_events.append({
                    "summary": item.get("summary", "Untitled"),
                    "start_time": fmt_time(start_raw),
                    "link": item.get("hangoutLink", item.get("location", ""))
                })
    except Exception as e:
        print(f"Calendar error: {e}")

    stats = db.get_meeting_stats(user_email=email)
    recent = db.get_all_meetings(user_email=email, limit=5)
    
    # Process recent meetings to include formatted time
    for m in recent:
        m['start_time'] = fmt_time(m['start_time'])

    # Get profile for sidebar
    profile = db.get_user_profile(email) or {}

    return {
        "user": {
            "name": profile.get("name", user["name"]),
            "email": email,
            "picture": profile.get("picture", user.get("picture", "https://api.dicebear.com/7.x/avataaars/svg?seed="+email))
        },
        "stats": {
            "total_meetings": stats.get('total_meetings', 0),
            "total_hours": stats.get('total_duration_hours', 0),
            "action_items_count": stats.get('total_words', 0),
            "participant_count": stats.get('avg_participants', 0)
        },
        "recent_meetings": recent,
        "events": calendar_events,
        "integrations": {
            "google": True if db.get_user_token(email) else False,
            "zoom": True if profile.get("zoom_token") else False 
        },
        "preferences": {
            "bot_name": profile.get("bot_name", "Renata AI | Assistant"),
            "auto_join": bool(profile.get("bot_auto_join", 1)),
            "recording": bool(profile.get("bot_recording_enabled", 1))
        }
    }

# ============================================================
# REPORTS / HISTORY
# ============================================================

@app.get("/reports", response_class=HTMLResponse)
async def reports_page_spa(request: Request):
    require_user(request)
    return FileResponse(os.path.join(BASE_DIR, "v3-frontend", "index.html"))

@app.get("/reports_data")
async def reports_data_api(request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    meetings = db.get_all_meetings(user_email=user['email'], limit=50)
    for m in meetings:
        m['start_time'] = fmt_time(m['start_time'])
    return {"meetings": meetings}

@app.get("/live/status")
async def live_status(request: Request):
    user = get_current_user(request)
    if not user: return {"status": "IDLE"}
    active = db.get_active_joining_meeting()
    return {"status": active['bot_status'] if active else "IDLE", "meeting": active}


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
async def analytics_page_spa(request: Request):
    require_user(request)
    return FileResponse(os.path.join(BASE_DIR, "v3-frontend", "index.html"))

# ============================================================
# AI SEARCH ASSISTANT
# On Vercel: uses Gemini API directly on database transcripts (no torch needed)
# Locally: can also use ChromaDB via rag_assistant module if available
# ============================================================

@app.get("/search", response_class=HTMLResponse)
async def search_page_spa(request: Request):
    require_user(request)
    return FileResponse(os.path.join(BASE_DIR, "v3-frontend", "index.html"))

def _get_kb_stats(user_email=None):
    """Return stats about indexed meetings from the database."""
    try:
        meetings = db.get_all_meetings(user_email=user_email, limit=500)
        meetings_with_transcript = [m for m in meetings if m.get('transcript_text') or m.get('summary_text')]
        return {
            "pdf_count": len(meetings_with_transcript),
            "indexed_segments": len(meetings_with_transcript),
            "status": "ready" if meetings_with_transcript else "empty"
        }
    except Exception as e:
        return {"pdf_count": 0, "indexed_segments": 0, "status": "error"}

@app.post("/search/ask", response_class=JSONResponse)
async def search_ask(request: Request, question: str = Form(...)):
    user = require_user(request)
    try:
        import google.generativeai as genai
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

        # Gather transcripts from database
        meetings = db.get_all_meetings(user_email=user['email'], limit=30)
        context_parts = []
        for m in meetings:
            if m.get('transcript_text') or m.get('summary_text'):
                title = m.get('title', 'Untitled')
                date = m.get('start_time', '')[:10]
                content = m.get('summary_text') or m.get('transcript_text', '')
                context_parts.append(f"--- Meeting: {title} ({date}) ---\n{content[:2000]}")

        if not context_parts:
            return {"answer": "No meeting transcripts found yet. Run the local bot pilot to record meetings first, then try again.", "success": True}

        context = "\n\n".join(context_parts[:15])  # Use up to 15 most recent
        prompt = f"""You are Renata, an AI meeting intelligence assistant. Answer the user's question based ONLY on the meeting transcripts provided below. If the answer is not found in the transcripts, say so clearly.

MEETING TRANSCRIPTS:
{context}

USER QUESTION: {question}

ANSWER:"""

        for model_name in ["gemini-2.0-flash", "gemini-1.5-flash"]:
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(prompt)
                return {"answer": response.text, "success": True}
            except Exception:
                continue
        return {"answer": "Could not get a response from the AI model. Please check your GEMINI_API_KEY.", "success": False}
    except Exception as e:
        return {"answer": f"Search error: {str(e)}", "success": False}

@app.post("/search/index", response_class=JSONResponse)
async def search_index(request: Request):
    """Re-sync knowledge base stats from database."""
    user = get_current_user(request)
    if not user: raise HTTPException(status_code=401)
    stats = _get_kb_stats(user_email=user['email'])
    return {
        "success": True,
        "message": f"Knowledge base ready. {stats['indexed_segments']} meeting reports indexed.",
        "indexed_segments": stats["indexed_segments"]
    }

@app.get("/search/status", response_class=JSONResponse)
async def search_status(request: Request):
    user = get_current_user(request)
    if not user: raise HTTPException(status_code=401)
    return _get_kb_stats(user_email=user['email'])


# ============================================================
# INTEGRATIONS
# ============================================================

@app.get("/integrations", response_class=HTMLResponse)
async def integrations_page_spa(request: Request):
    require_user(request)
    return FileResponse(os.path.join(BASE_DIR, "v3-frontend", "index.html"))

# ============================================================
# ADD LIVE MEETING
# ============================================================

@app.get("/live", response_class=HTMLResponse)
async def live_page_spa(request: Request):
    require_user(request)
    return FileResponse(os.path.join(BASE_DIR, "v3-frontend", "index.html"))

@app.post("/live/join", response_class=JSONResponse)
async def live_join(request: Request, meeting_url: str = Form(...)):
    user = require_user(request)
    # On Vercel, we can't launch subprocesses. 
    # We create a 'JOIN_PENDING' meeting entry that the local pilot will pick up.
    m_id = f"join_{int(time.time())}"
    db.exec_commit('''
        INSERT INTO meetings (meeting_id, title, start_time, meet_url, user_email, bot_status, bot_status_note)
        VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?, 'JOIN_PENDING', 'Waiting for local bot pilot...')
    ''', (m_id, "Live Meeting", meeting_url, user['email']))
    
    return {"success": True, "message": "Renata has been alerted. Make sure your local pilot script is running!"}

@app.post("/settings/api/save")
async def settings_api_save(request: Request):
    user = require_user(request)
    data = await request.json()
    
    settings = {}
    if "name" in data: settings["name"] = data["name"]
    if "bot_name" in data: settings["bot_name"] = data["bot_name"]
    if "auto_join" in data: settings["bot_auto_join"] = 1 if data["auto_join"] else 0
    if "recording" in data: settings["bot_recording_enabled"] = 1 if data["recording"] else 0
    
    if settings:
        db.update_user_profile(user["email"], settings)
        
    # Update local session for UI consistency if name changed
    if "name" in data and "user" in request.session:
        request.session["user"]["name"] = data["name"]
        
    return {"success": True}

@app.get("/live/status", response_class=JSONResponse)
async def live_status(request: Request):
    user = require_user(request)
    meeting = db.get_active_joining_meeting()
    if meeting:
        return {
            "active": True,
            "status": meeting.get("bot_status", "UNKNOWN"),
            "note": meeting.get("bot_status_note", "")
        }
    return {"active": False}

# ============================================================
# SETTINGS / PROFILE
# ============================================================

@app.get("/settings", response_class=HTMLResponse)
async def settings_page_spa(request: Request):
    require_user(request)
    return FileResponse(os.path.join(BASE_DIR, "v3-frontend", "index.html"))

@app.post("/settings/save")
async def settings_save(request: Request, name: str = Form(""), bot_name: str = Form("")):
    user = require_user(request)
    db.update_user_profile(user["email"], {"name": name, "bot_name": bot_name})
    request.session["user"]["name"] = name
    return RedirectResponse("/settings?msg=Saved+successfully", status_code=303)

@app.post("/account/delete")
async def delete_account(request: Request):
    """Permanently delete the user's account and all their data."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    db.delete_user_account(user["email"])
    request.session.clear()
    return RedirectResponse("/login?msg=Account+deleted", status_code=303)

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


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

# Duplicate routes at the end removed.

# ============================================================
# HEALTH CHECK (Railway uses this)
# ============================================================

@app.get("/health")
async def health():
    return {"status": "ok", "service": "RENATA Meeting Intelligence"}
