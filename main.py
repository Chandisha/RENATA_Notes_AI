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
import io
from pathlib import Path
import smtplib
from email.message import EmailMessage
from starlette.middleware.sessions import SessionMiddleware
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import Optional
from dotenv import load_dotenv

load_dotenv(override=True)

from fastapi import FastAPI, Request, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse, StreamingResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import meeting_database as db
from payment_service import razorpay_service
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
import googleapiclient.discovery

# --- Zoom OAuth Constants ---
ZOOM_CLIENT_ID = (os.getenv("ZOOM_CLIENT_ID") or "").strip()
ZOOM_CLIENT_SECRET = (os.getenv("ZOOM_CLIENT_SECRET") or "").strip()
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

if (BASE_DIR / "logo_img").exists():
    app.mount("/logo_img", StaticFiles(directory=str(BASE_DIR / "logo_img")), name="logo_img")

if (BASE_DIR / "v3-frontend").exists():
    app.mount("/v3-frontend", StaticFiles(directory=str(BASE_DIR / "v3-frontend")), name="v3-frontend")

# Robust path detection for Vercel vs Local
templates_dir = BASE_DIR / "templates"
if not templates_dir.exists():
    # Fallback to current working directory if BASE_DIR detection fails in serverless
    templates_dir = Path("templates")
    
if templates_dir.exists():
    templates = Jinja2Templates(directory=str(templates_dir))
    print(f">>> TEMPLATES INITIALIZED FROM: {templates_dir.absolute()}")
else:
    print("WARNING: Templates directory not found anywhere!")
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

@app.get("/api/me")
async def get_me(request: Request):
    """Fast endpoint for basic profile info."""
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    db_user = db.get_user_profile(user['email'])
    if db_user:
        return {
            "user": {
                "email": db_user['email'],
                "name": db_user['name'],
                "picture": db_user['picture'],
                "plan": db_user.get('subscription_plan', 'Free')
            },
            "preferences": {
                "bot_name": db_user.get('bot_name'),
                "auto_join": db_user.get('bot_auto_join'),
                "recording": db_user.get('bot_recording_enabled')
            }
        }
    return {"user": user}

def require_user(request: Request):
    user = get_current_user(request)
    if not user:
        # Strict requirement: No session = No entry. 
        # For API routes it returns 401 which the frontend handles.
        # For Page routes we handle redirection explicitly.
        raise HTTPException(status_code=401, detail="Authentication required")
    
    # Optional: Keep profile updated if they are logged in
    try:
        db.upsert_user(user["email"], user.get("name"), user.get("picture"))
    except:
        pass
        
    return user

# --- Google OAuth Flow Helper ---
def create_google_flow(request: Request):
    """Create a Flow object from credentials.json or GOOGLE_CREDENTIALS_JSON env var."""
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    
    # Use the new professional domain for production
    if os.getenv("VERCEL_ENV"):
        redirect_uri = "https://meet.nexren.ai/auth/callback"
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
    """Entry point. Renders login or dashboard directly to avoid confuses redirects for bots."""
    host = request.headers.get("host", "")
    if "vercel.app" in host and host != "meet.nexren.ai" and not host.startswith("localhost"):
        # For historical SEO/Redirect only
        return RedirectResponse("https://meet.nexren.ai/")

    user = get_current_user(request)
    if user:
        return RedirectResponse("/dashboard")
        
    # Render login directly at the root for unauthenticated users
    error = request.query_params.get("error")
    if not templates:
        return HTMLResponse("Templates not initialized. Check server logs.", status_code=500)
    return templates.TemplateResponse(request=request, name="login.html", context={"error": error})

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Explicit login page. Renders same template as root."""
    host = request.headers.get("host", "")
    if "vercel.app" in host and host != "meet.nexren.ai" and not host.startswith("localhost"):
        return RedirectResponse("https://meet.nexren.ai/login")

    user = get_current_user(request)
    if user:
        return RedirectResponse("/dashboard")
        
    error = request.query_params.get("error")
    if not templates:
        return HTMLResponse("Templates not initialized. Check server logs.", status_code=500)
    return templates.TemplateResponse(request=request, name="login.html", context={"error": error})

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login")

@app.get("/privacy")
async def privacy_page(request: Request):
    """Professional Privacy Policy required for Google Oauth Verification."""
    return HTMLResponse("""
    <html>
        <head>
            <title>Privacy Policy - MeetAI</title>
            <style>
                body { font-family: sans-serif; line-height: 1.6; padding: 40px; max-width: 800px; margin: auto; color: #333; }
                header { border-bottom: 2px solid #3b82f6; padding-bottom: 20px; margin-bottom: 40px; }
                h1 { color: #1e3a8a; }
                h2 { color: #1e40af; margin-top: 30px; }
                .notice { background: #eff6ff; border-left: 4px solid #3b82f6; padding: 15px; margin: 20px 0; font-style: italic; }
                footer { margin-top: 50px; font-size: 0.8em; color: #666; border-top: 1px solid #ddd; padding-top: 20px; }
            </style>
        </head>
        <body>
            <header>
                <h1>Privacy Policy</h1>
                <p><strong>Effective Date: March 30, 2026</strong></p>
                <p><strong>Entity: MeetAI (operated by Nexren)</strong></p>
            </header>

            <section>
                <h2>1. Introduction</h2>
                <p>MeetAI ("we," "us," or "our") provides an AI-powered meeting assistant. This policy explains how we collect, use, and protect your information when you use our service, particularly regarding your Google and Zoom integrations.</p>
            </section>

            <section>
                <h2>2. Data We Collect via Google APIs</h2>
                <p>Our application requests access to the following <strong>Google User Data</strong> to provide its core service:</p>
                <ul>
                    <li><strong>Google Calendar:</strong> To identify upcoming meeting invitations and dispatch our transcription bot.</li>
                    <li><strong>Gmail (Read-Only & Send):</strong> To detect meeting invites sent via email and provide contextual briefs to participants before meetings.</li>
                    <li><strong>Google Drive Metadata:</strong> Only to identify meeting-related files to enhance the accuracy of generated summaries.</li>
                </ul>
            </section>

            <section class="notice">
                <h2>3. Limited Use Disclosure</h2>
                <p><strong>MeetAI's use and transfer to any other app of information received from Google APIs will adhere to the <a href="https://developers.google.com/terms/api-services-user-data-policy" target="_blank">Google API Services User Data Policy</a>, including the Limited Use requirements.</strong></p>
            </section>

            <section>
                <h2>4. Data Storage and Security</h2>
                <p>All data retrieved from your integrations (transcripts, calendars, and email snippets) is stored on our secure servers and is never shared with third-party advertisers. We use industry-standard encryption for data at rest and in transit.</p>
            </section>

            <section>
                <h2>5. Data Deletion and Control</h2>
                <p>You can revoke access to your Google or Zoom accounts at any time via the "Integrations" tab in the dashboard. You may also permanently delete your account and all associated meeting data via the "Settings" page.</p>
            </section>

            <footer>
                <p>For privacy inquiries, contact us at: renata@renataiot.com</p>
                <p><a href="/terms">Terms of Service</a> | <a href="/">Back to Dashboard</a></p>
            </footer>
        </body>
    </html>
    """)

@app.get("/terms")
async def terms_page(request: Request):
    """Basic Terms of Service for Google Verification."""
    return HTMLResponse("""
    <html>
        <head>
            <title>Terms of Service - MeetAI</title>
            <style>
                body { font-family: sans-serif; line-height: 1.6; padding: 40px; max-width: 800px; margin: auto; color: #333; }
                h1 { color: #1e3a8a; }
            </style>
        </head>
        <body>
            <h1>Terms of Service</h1>
            <p><strong>Last Updated: March 30, 2026</strong></p>
            <p>By using MeetAI, you agree to allow our AI bot to join and record meetings you specify. We are not responsible for any misuse of the generated notes by the user.</p>
            <p>The service is provided "as is" and you agree to comply with your organization's internal recording policies before using the bot.</p>
            <a href="/">Back to Home</a>
        </body>
    </html>
    """)

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
        existing_user = db.fetch_one("SELECT email FROM users WHERE LOWER(email) = LOWER(?)", (email,))
        if existing_user:
            db.exec_commit("""
                UPDATE users SET 
                    name = ?, 
                    picture = ?, 
                    google_token = ?, 
                    updated_at = CURRENT_TIMESTAMP 
                WHERE LOWER(email) = LOWER(?)
            """, (name, picture, creds.to_json(), email))
        else:
            db.exec_commit("""
                INSERT INTO users (email, name, picture, google_token) 
                VALUES (?, ?, ?, ?)
            """, (email.lower(), name, picture, creds.to_json()))
        
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
    if not get_current_user(request):
        return RedirectResponse("/login")
    return FileResponse(os.path.join(BASE_DIR, "v3-frontend", "index.html"))

# --- DISK-PERSISTENT CALENDAR CACHE ---
import json
CALENDAR_CACHE_FILE = "calendar_mirror_cache.json"

def _load_persistent_cache():
    if os.path.exists(CALENDAR_CACHE_FILE):
        try:
            with open(CALENDAR_CACHE_FILE, "r") as f:
                return json.load(f)
        except: return {}
    return {}

def _save_persistent_cache(cache_data):
    try:
        # Shallow copy to avoid runtime errors during iteration
        with open(CALENDAR_CACHE_FILE, "w") as f:
            json.dump(cache_data, f)
    except: pass

_calendar_cache = _load_persistent_cache()
CALENDAR_CACHE_TTL = 15  # Fast re-sync in background

@app.get("/dashboard_data")
async def dashboard_data(request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized", "redirect": "/login"}, status_code=401)
    
    email = user['email']
    force = request.query_params.get("force") == "true"

    # ---- Run Calendar fetch + DB queries concurrently ----
    import asyncio

    async def fetch_calendar():
        """Fetch Google Calendar events — with 30s cache to avoid slow repeat loads."""
        # Check cache first (unless force=True)
        cached = _calendar_cache.get(email)
        if not force and cached and (time.time() - cached["ts"]) < CALENDAR_CACHE_TTL:
            return cached["events"], cached["count"]
        
        def _sync_fetch():
            events = []
            count = 0
            try:
                creds = get_user_credentials(email)
                if creds:
                    # static_discovery=False avoids a network call to fetch the discovery document
                    from googleapiclient.discovery import build
                    svc = build("calendar", "v3", credentials=creds, static_discovery=False)
                    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                    result = svc.events().list(
                        calendarId="primary", timeMin=now_iso,
                        maxResults=10, singleEvents=True, orderBy="startTime"
                    ).execute()
                    items = result.get("items", [])
                    count = len(items)
                    
                    # Batch fetch skipping status for all meetings at once
                    m_ids = [item.get("id") for item in items if item.get("id")]
                    db_meetings = {m['meeting_id']: m for m in db.get_meetings_by_ids(m_ids, email)}

                    for item in items:
                        start_raw = item['start'].get('dateTime', item['start'].get('date'))
                        m_id = item.get("id")
                        
                        # Link detection logic
                        link = item.get("hangoutLink")
                        if not link:
                            conf = item.get("conferenceData", {})
                            for ep in conf.get("entryPoints", []):
                                if ep.get("entryPointType") == "video":
                                    link = ep.get("uri")
                                    break
                        if not link:
                            link = item.get("location", "")
                        
                        # Quick lookup from our batched results
                        db_meeting = db_meetings.get(m_id)
                        is_enabled = True
                        if db_meeting:
                            is_enabled = not bool(db_meeting.get('is_skipped', 0))

                        events.append({
                            "id": m_id or f"untracked-{time.time()}",
                            "summary": item.get("summary", "Untitled"),
                            "start_time": fmt_time(start_raw),
                            "link": link or "",
                            "is_enabled": is_enabled
                        })
            except Exception as e:
                print(f"Calendar fetch error: {e}")
            return events, count
        async def _run_fetch_and_update():
            res = await asyncio.to_thread(_sync_fetch)
            _calendar_cache[email] = {"events": res[0], "count": res[1], "ts": time.time()}
            _save_persistent_cache(_calendar_cache) # Persist to disk
            return res

        # STALE-WHILE-REVALIDATE PATTERN:
        # If we have cache, return it IMMEDIATELY and update in background
        if cached:
            # Trigger background refresh if it's been more than 15s
            if (time.time() - cached["ts"]) > 15:
                asyncio.create_task(_run_fetch_and_update())
            return cached["events"], cached["count"]

        # If no cache at all, we must wait but we'll use the optimized fetch
        result = await _run_fetch_and_update()
        return result

    # Run calendar fetch and DB reads in parallel
    calendar_task = asyncio.create_task(fetch_calendar())

    # These are all fast local DB calls - run immediately
    db_user = db.get_user_profile(email)
    recent = db.get_all_meetings(user_email=email, limit=5)
    profile = db.get_user_profile(email) or {}

    # Now await calendar (it's been running in background while DB was queried)
    calendar_events, upcoming_meetings_count = await calendar_task

    stats = db.get_meeting_stats(user_email=email, upcoming_count=upcoming_meetings_count)

    user_payload = {
        "email": email,
        "name": db_user['name'] if db_user else user.get('name'),
        "picture": db_user['picture'] if db_user else user.get('picture'),
        "plan": db_user.get('subscription_plan', 'Free') if db_user else 'Free'
    }

    for m in recent:
        m['start_time'] = fmt_time(m['start_time'])

    return {
        "user": user_payload,
        "stats": {
            "total_meetings": stats.get('total_meetings', 0),
            "total_hours": stats.get('total_duration_hours', 0),
            "action_items_count": stats.get('total_reports', 0),
            "participant_count": stats.get('avg_participants', 0)
        },
        "recent_meetings": recent,
        "events": calendar_events,
        "integrations": {
            "google": True if db.get_user_token(email) else False,
            "zoom": True if profile.get("zoom_token") else False
        },
        "preferences": {
            "bot_name": profile.get("bot_name", "MeetAI | Assistant"),
            "auto_join": bool(profile.get("bot_auto_join", 1) if profile.get("bot_auto_join") is not None else 1),
            "recording": bool(profile.get("bot_recording_enabled", 1) if profile.get("bot_recording_enabled") is not None else 1)
        }
    }

@app.post("/settings/toggle_global_bot")
async def toggle_global_bot_api(request: Request):
    user = require_user(request)
    data = await request.json()
    enabled = data.get("enabled", True)
    db.update_user_profile(user['email'], {"bot_auto_join": 1 if enabled else 0})
    return {"success": True}

@app.post("/meetings/toggle_bot")
async def toggle_meeting_bot_api(request: Request):
    user = require_user(request)
    data = await request.json()
    m_id = data.get("meeting_id")
    enabled = data.get("enabled", True)
    
    # Check if meeting exists, if not create a minimal one
    db_meeting = db.get_meeting(m_id, user_email=user['email'])
    if not db_meeting:
        db.exec_commit('''
            INSERT INTO meetings (meeting_id, title, start_time, user_email, meet_url, is_skipped)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (m_id, data.get("summary", "Upcoming Session"), data.get("start_time", datetime.now().isoformat()), user['email'], data.get("link", ""), 0 if enabled else 1))
    else:
        db.update_meeting(m_id, {"is_skipped": 0 if enabled else 1}, user_email=user['email'])
    
    return {"success": True}

# ============================================================
# PAYMENTS (RAZORPAY)
# ============================================================

@app.post("/payments/create_order")
async def create_payment_order(request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    try:
        data = await request.json()
        item_type = data.get("item_type", "single_meeting")
        meeting_id = data.get("meeting_id")
        
        order_data = razorpay_service.create_order(user['email'], item_type, meeting_id)
        return JSONResponse(order_data)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/payments/verify")
async def verify_payment(request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    try:
        data = await request.json()
        success, message = razorpay_service.verify_payment(
            data['razorpay_order_id'],
            data['razorpay_payment_id'],
            data['razorpay_signature'],
            user['email'],
            data.get('item_type'),
            data.get('meeting_id')
        )
        
        if success:
            return JSONResponse({"status": "success", "message": message})
        else:
            return JSONResponse({"status": "error", "message": message}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ============================================================
# REPORTS / HISTORY
# ============================================================

@app.get("/reports", response_class=HTMLResponse)
async def reports_page_spa(request: Request):
    if not get_current_user(request):
        return RedirectResponse("/login")
    return FileResponse(os.path.join(BASE_DIR, "v3-frontend", "index.html"))

@app.get("/reports_data")
async def reports_data_api(request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    # Only show meetings that are actual reports (have content)
    meetings = db.get_all_meetings(user_email=user['email'], limit=50, reports_only=True)

    stats = db.get_meeting_stats(user['email'])
    total_count = stats.get('total_reports', 0)
    
    # MULTI-USER FIX: Add PDF availability status for each meeting
    for m in meetings:
        m['start_time'] = fmt_time(m['start_time'])
        
        # Check if PDFs are available (file on disk or blob in DB)
        m['pdf_available'] = False
        m['transcripts_pdf_available'] = False
        
        if m.get('pdf_path'):
            m['pdf_available'] = os.path.exists(m['pdf_path']) or bool(m.get('pdf_blob'))
            if m['pdf_available']:
                pdf_name = m['pdf_path'].split('/')[-1].split('\\')[-1]
                m['pdf_download_link'] = f"/download/pdf/{pdf_name}"
        
        if m.get('transcripts_pdf_path'):
            m['transcripts_pdf_available'] = os.path.exists(m['transcripts_pdf_path']) or bool(m.get('transcripts_pdf_blob'))
            if m['transcripts_pdf_available']:
                transcript_name = m['transcripts_pdf_path'].split('/')[-1].split('\\')[-1]
                m['transcripts_pdf_download_link'] = f"/download/transcripts_pdf/{transcript_name}"
        
    return {"meetings": meetings, "total_count": total_count}

@app.get("/api/meeting/{meeting_id}/summary")
async def get_quick_meeting_summary(meeting_id: str, request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    meeting = db.get_meeting(meeting_id, user_email=user['email'])
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
        
    transcript = meeting.get('transcript_text')
    if not transcript:
        return {"summary": "No transcript available for this meeting yet."}
    
    try:
        from meeting_notes_generator import get_quick_bullet_summary
        # The function was added to meeting_notes_generator.py in a previous step
        summary = get_quick_bullet_summary(transcript)
        return {"summary": summary}
    except Exception as e:
        return {"summary": f"Error: {str(e)}"}

@app.delete("/reports/{meeting_id}")
async def delete_meeting_report(meeting_id: str, request: Request):
    user = require_user(request)
    success = db.delete_meeting(meeting_id, user['email'])
    if success:
        return {"success": True}
    raise HTTPException(status_code=404, detail="Meeting not found")

@app.get("/live/status", response_class=JSONResponse)
async def live_status(request: Request):
    user = get_current_user(request)
    if not user: return {"active": False, "status": "IDLE"}

    # 1. Check for a truly active meeting (bot is in progress right now)
    meeting = db.get_active_joining_meeting(user['email'])
    if meeting:
        return {
            "active": True,
            "status": meeting.get("bot_status", "UNKNOWN"),
            "note": meeting.get("bot_status_note", ""),
            "meeting_id": meeting.get("meeting_id")
        }

    # 2. Check for a recently finished meeting (show COMPLETED/FAILED briefly for 2 min)
    finished = db.get_recently_finished_meeting(user['email'])
    if finished:
        return {
            "active": True,
            "status": finished.get("bot_status", "COMPLETED"),
            "note": finished.get("bot_status_note", ""),
            "meeting_id": finished.get("meeting_id")
        }

    # 3. Nothing active — bot is idle
    return {"active": False, "status": "IDLE"}


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
    if not templates:
        raise HTTPException(status_code=500, detail="Templates not initialized")
        
    return templates.TemplateResponse(request=request, name="report_detail.html", context={
        "user": user,
        "meeting": meeting,
        "active_page": "reports"
    })

# ============================================================
# ANALYTICS
# ============================================================

@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page_spa(request: Request):
    if not get_current_user(request):
        return RedirectResponse("/login")
    return FileResponse(os.path.join(BASE_DIR, "v3-frontend", "index.html"))

@app.get("/analytics/data", response_class=JSONResponse)
async def analytics_data(request: Request):
    user = require_user(request)
    email = user['email']
    
    # 5. Add Upcoming Meetings Count from Google Calendar (Match Dashboard Logic)
    upcoming_count = 0
    try:
        creds = get_user_credentials(email)
        if creds:
            from googleapiclient.discovery import build
            svc = build("calendar", "v3", credentials=creds)
            now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            result = svc.events().list(
                calendarId="primary", timeMin=now_iso,
                maxResults=15, singleEvents=True, orderBy="startTime"
            ).execute()
            items = result.get("items", [])
            upcoming_count = len(items)
    except Exception as e:
        print(f"Analytics Calendar Error: {e}")
        
    stats = db.get_meeting_stats(user_email=email, upcoming_count=upcoming_count)
    return stats

# ============================================================
# AI SEARCH ASSISTANT
# On Vercel: uses Gemini API directly on database transcripts (no torch needed)
# Locally: can also use ChromaDB via rag_assistant module if available
# ============================================================

@app.get("/search", response_class=HTMLResponse)
async def search_page_spa(request: Request):
    if not get_current_user(request):
        return RedirectResponse("/login")
    return FileResponse(os.path.join(BASE_DIR, "v3-frontend", "index.html"))

def _get_kb_stats(user_email=None, plan='Free'):
    """Return stats about indexed meetings from the database based on account type."""
    try:
        stats = db.get_meeting_stats(user_email=user_email)
        total = stats.get('total_reports', 0)
        return {
            "pdf_count": total,
            "indexed_segments": total,
            "status": "ready" if total > 0 else "empty"
        }
    except Exception as e:
        return {"pdf_count": 0, "indexed_segments": 0, "status": "error"}

@app.get("/chat/sessions")
async def list_chat_sessions(request: Request):
    user = require_user(request)
    sessions = db.get_chat_sessions(user['email'])
    return {"sessions": sessions}

@app.post("/chat/sessions")
async def create_new_session(request: Request):
    user = require_user(request)
    session_id = f"chat_{int(time.time() * 1000)}"
    db.create_chat_session(user['email'], session_id)
    return {"session_id": session_id}

@app.get("/chat/sessions/{session_id}/messages")
async def list_chat_messages(session_id: str, request: Request):
    user = require_user(request)
    messages = db.get_chat_messages(session_id)
    return {"messages": messages}

@app.delete("/chat/sessions/{session_id}")
async def delete_chat_session(session_id: str, request: Request):
    user = require_user(request)
    db.delete_chat_session(session_id, user['email'])
    return {"success": True}


# ============================================================
# HELP & SUPPORT TICKETS
# ============================================================

def _send_support_email(user_email, subject, query):
    """Sends a support ticket email to the company from the bot mail."""
    try:
        msg = EmailMessage()
        msg['Subject'] = f"SUPPORT TICKET: {subject}"
        support_email = os.getenv("BOT_EMAIL")
        support_pass = os.getenv("BOT_PASSWORD")
        
        msg['From'] = support_email
        msg['To'] = support_email  # Company support email
        
        body = f"User: {user_email}\nSubject: {subject}\n\nQuery/Issue:\n{query}\n\n---\nSent from Renata Meeting Assistant Support System"
        msg.set_content(body)
        
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(support_email, support_pass)
            smtp.send_message(msg)
        return True
    except Exception as e:
        print(f"Failed to send support email: {e}")
        return False

@app.get("/help/tickets", response_class=JSONResponse)
async def list_active_tickets(request: Request):
    user = require_user(request)
    tickets = db.get_active_tickets(user['email'])
    return {"success": True, "tickets": tickets}

@app.post("/help/tickets", response_class=JSONResponse)
async def submit_help_ticket(request: Request, subject: str = Form(...), query: str = Form(...)):
    user = require_user(request)
    
    # Save to database
    db.create_ticket(user['email'], subject, query)
    
    # Send email
    _send_support_email(user['email'], subject, query)
    
    return {"success": True, "message": "Your ticket has been raised. Our team will review it shortly."}


@app.post("/search/ask", response_class=JSONResponse)
async def search_ask(request: Request, question: str = Form(...), session_id: Optional[str] = Form(None)):
    user = require_user(request)
    api_key = os.getenv("GEMINI_API_KEY")
    
    if not api_key or len(api_key) < 5:
        return {"answer": "GEMINI_API_KEY is missing. Please add it to your environment.", "success": False}

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)

        # --- 1. Quick Greetings Check ---
        lower_q = question.strip().lower()
        if lower_q in ["hi", "hello", "hey", "hi there", "hello there", "greetings"]:
            ans = "Hello, I am Renata! I can share information from your reports. What do you want to know?"
            if session_id:
                past_msgs = db.get_chat_messages(session_id)
                if not past_msgs:
                    db.rename_chat_session(session_id, "Greeting")
                db.add_chat_message(session_id, "user", question)
                db.add_chat_message(session_id, "assistant", ans)
            return {"answer": ans, "success": True, "session_id": session_id}

        # --- 2. Get History if session_id is provided ---
        history_context = ""
        is_first_message = False
        if session_id:
            past_messages = db.get_chat_messages(session_id)
            if not past_messages:
                is_first_message = True
            for msg in past_messages[-10:]: # Last 10 messages for context
                history_context += f"{msg['role'].upper()}: {msg['content']}\n"
            db.add_chat_message(session_id, "user", question)

        # --- 3. Gather Reports (Meetings) from database ---
        # Sort by start_time DESC to help with "last report" queries
        meetings = db.get_all_meetings(user['email'], limit=30, order_by="start_time DESC")
        context_parts = []
        
        # Get actual user record for plan info to ensure accuracy
        db_user = db.get_user_profile(user['email'])
        user_plan = db_user.get('subscription_plan', 'Free') if db_user else 'Free'
        
        for i, m in enumerate(meetings):
            if m.get('transcript_text') or m.get('summary_text'):
                title = m.get('title', 'Untitled')
                date = m.get('start_time', '')[:19]
                
                # Pro users get the full 'major' report (summary), others get transcripts
                if user_plan == 'Pro':
                    content = m.get('summary_text') or m.get('transcript_text', '')
                else:
                    content = m.get('transcript_text') or m.get('summary_text', '')
                
                # Specifically tag the most recent one
                tag = " (MOST RECENT REPORT)" if i == 0 else ""
                context_parts.append(f"--- REPORT {i+1}{tag}: {title} | DATE: {date} ---\n{content[:15000]}")

        if not context_parts:
            return {"answer": "No meeting reports found in your knowledge base.", "success": True}

        context = "\n\n".join(context_parts)
        
        system_instruction = f"""You are Renata Intelligence Assistant. 
The user refers to meeting summaries/PDFs as 'Reports'. 
When the user asks about the 'last report' or 'latest report', they mean REPORT 1 (the most recent one chronologically).

KNOWLEDGE BASE (Meeting Reports):
{context}

PREVIOUS CONVERSATION:
{history_context}
"""
        
        prompt = f"{system_instruction}\n\nUSER QUESTION: {question}\n\nDETAILED ANSWER:"

        last_err = "No models responded."
        requested_models = ["gemini-3-flash-preview", "gemini-2.5-flash"]
        
        final_response = None
        for model_name in requested_models:
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(prompt)
                if response and response.text:
                    final_response = response.text
                    break
            except Exception as model_err:
                last_err = str(model_err)
                continue
                
        if final_response:
            if session_id:
                db.add_chat_message(session_id, "assistant", final_response)
                
                # If first message, generate a dynamic title
                if is_first_message:
                    try:
                        title_model = genai.GenerativeModel("gemini-3-flash-preview")
                        title_prompt = f"Given the user question: '{question}', generate a very short 2-4 word topic-based title for this chat session. Just output the title, nothing else. If it is a greeting, say 'Greeting'."
                        title_resp = title_model.generate_content(title_prompt)
                        if title_resp and title_resp.text:
                            new_title = title_resp.text.strip().replace('"', '').replace("'", "")
                            db.rename_chat_session(session_id, new_title)
                    except: pass
                    
            return {"answer": final_response, "success": True, "session_id": session_id}
            
        return {"answer": f"Gemini Error: {last_err}", "success": False}
    except Exception as e:
        return {"answer": f"Engine Error: {str(e)}", "success": False}

@app.post("/search/index", response_class=JSONResponse)
async def search_index(request: Request):
    """Re-sync knowledge base stats from database."""
    user = get_current_user(request)
    if not user: raise HTTPException(status_code=401)
    
    # Get actual user record for plan info
    db_user = db.get_user_profile(user['email'])
    plan = db_user.get('subscription_plan', 'Free') if db_user else 'Free'
    
    stats = _get_kb_stats(user_email=user['email'], plan=plan)
    return {
        "success": True,
        "message": f"Knowledge base ready. {stats['indexed_segments']} meeting reports indexed ({plan} Account).",
        "indexed_segments": stats["indexed_segments"]
    }

    return _get_kb_stats(user_email=user['email'], plan=plan)

# ============================================================
# PERSONAL NOTES & AI INSIGHTS API
# ============================================================

@app.get("/api/notes/list", response_class=JSONResponse)
async def api_personal_notes_list(request: Request):
    user = require_user(request)
    notes = db.fetch_all("SELECT id, title, updated_at FROM personal_notes WHERE user_email = ? ORDER BY updated_at DESC", (user['email'],))
    return {"notes": notes}

@app.get("/api/notes/personal/{note_id}", response_class=JSONResponse)
async def api_get_personal_note(request: Request, note_id: int):
    user = require_user(request)
    note = db.fetch_one("SELECT id, title, content FROM personal_notes WHERE id = ? AND user_email = ?", (note_id, user['email']))
    if not note: raise HTTPException(status_code=404)
    return note

@app.post("/api/notes/personal/save", response_class=JSONResponse)
async def api_save_personal_note(request: Request):
    user = require_user(request)
    data = await request.json()
    note_id = data.get("id")
    title = data.get("title", "Untitled Note")
    content = data.get("content", "")
    
    if note_id:
        db.exec_commit("UPDATE personal_notes SET title = ?, content = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_email = ?", (title, content, note_id, user['email']))
        return {"success": True, "id": note_id}
    else:
        db.exec_commit("INSERT INTO personal_notes (user_email, title, content) VALUES (?, ?, ?)", (user['email'], title, content))
        # Get the new ID (Works for both SQLite and Postgres)
        row = db.fetch_one("SELECT id FROM personal_notes WHERE user_email = ? ORDER BY id DESC LIMIT 1", (user['email'],))
        return {"success": True, "id": row['id'] if row else None}

@app.post("/api/notes/personal/delete/{note_id}", response_class=JSONResponse)
async def api_delete_personal_note(request: Request, note_id: int):
    user = require_user(request)
    db.exec_commit("DELETE FROM personal_notes WHERE id = ? AND user_email = ?", (note_id, user['email']))
    return {"success": True}

@app.get("/api/notes/ai/list", response_class=JSONResponse)
async def api_ai_insights_list(request: Request):
    user = require_user(request)
    meetings = db.fetch_all("""
        SELECT meeting_id, title, start_time, bot_status, pdf_path, is_summarized_paid
        FROM meetings 
        WHERE user_email = ? 
        ORDER BY created_at DESC LIMIT 50
    """, (user['email'],))
    return {"meetings": meetings}

@app.get("/api/notes/ai/{meeting_id}", response_class=JSONResponse)
async def api_get_ai_insights(request: Request, meeting_id: str):
    user = require_user(request)
    m = db.fetch_one("""
        SELECT summary_text, action_items, title, status, bot_status, bot_status_note, pdf_path, transcripts_pdf_path, is_summarized_paid
        FROM meetings 
        WHERE meeting_id = ? AND user_email = ?
    """, (meeting_id, user['email']))
    
    if not m: raise HTTPException(status_code=404)
        
    ai_insights = ""
    if m.get('summary_text'):
        ai_insights += f"### Summary\n{m['summary_text']}\n\n"
    if m.get('action_items'):
        ai_insights += f"### Action Items\n{m['action_items']}\n\n"
    
    if m.get('bot_status_note') and "LIVE_INSIGHTS:" in m['bot_status_note']:
        live_part = m['bot_status_note'].split("LIVE_INSIGHTS:")[1].strip()
        ai_insights = f"### Live Captured Points\n{live_part}\n\n" + ai_insights

    if not ai_insights:
        if m.get('bot_status') in ['JOIN_PENDING', 'DISPATCHING', 'JOINING', 'CONNECTING', 'CONNECTED']:
            ai_insights = "Renata is currently in the meeting. AI insights will appear here soon..."
        elif m.get('status') == 'processing' or m.get('bot_status') == 'PROCESSING':
            ai_insights = "Meeting ended. Renata is generating the final AI intelligence report..."
        else:
            ai_insights = "No AI insights found for this meeting."

    # Construct PDF links if they exist
    pdf_link = None
    transcripts_pdf_link = None
    
    if m.get('pdf_path') and os.path.exists(m['pdf_path']):
        pdf_name = m['pdf_path'].split('/')[-1].split('\\')[-1]
        pdf_link = f"/download/pdf/{pdf_name}"
    
    if m.get('transcripts_pdf_path') and os.path.exists(m['transcripts_pdf_path']):
        transcripts_name = m['transcripts_pdf_path'].split('/')[-1].split('\\')[-1]
        transcripts_pdf_link = f"/download/transcripts_pdf/{transcripts_name}"

    return {
        "ai_notes": ai_insights,
        "title": m.get('title', 'Untitled Meeting'),
        "pdf_link": pdf_link,
        "transcripts_pdf_link": transcripts_pdf_link,
        "bot_status": m.get('bot_status', 'UNKNOWN'),
        "is_paid": m.get('is_summarized_paid', 0),
        "pdf_generated_at": m.get('updated_at')  # Let frontend know when PDF was last updated
    }


@app.get("/api/pdf_status/{meeting_id}", response_class=JSONResponse)
async def check_pdf_status(request: Request, meeting_id: str):
    """REAL-TIME CHECK: Frontend polls this to detect when PDFs become available."""
    user = require_user(request)
    m = db.fetch_one("""
        SELECT pdf_path, transcripts_pdf_path, bot_status, updated_at
        FROM meetings 
        WHERE meeting_id = ? AND user_email = ?
    """, (meeting_id, user['email']))
    
    if not m: 
        raise HTTPException(status_code=404)
    
    # Check if PDFs exist (on disk or in DB)
    pdf_available = False
    transcripts_pdf_available = False
    
    # Check local disk first
    if m.get('pdf_path'):
        pdf_available = os.path.exists(m['pdf_path'])
    
    if m.get('transcripts_pdf_path'):
        transcripts_pdf_available = os.path.exists(m['transcripts_pdf_path'])
    
    # If not on disk, check if blob exists in DB (Vercel/cloud)
    if not pdf_available and m.get('pdf_path'):
        blob_check = db.fetch_one("SELECT pdf_blob FROM meetings WHERE meeting_id = ? AND user_email = ?", 
                                  (meeting_id, user['email']))
        pdf_available = bool(blob_check and blob_check.get('pdf_blob'))
    
    if not transcripts_pdf_available and m.get('transcripts_pdf_path'):
        blob_check = db.fetch_one("SELECT transcripts_pdf_blob FROM meetings WHERE meeting_id = ? AND user_email = ?", 
                                  (meeting_id, user['email']))
        transcripts_pdf_available = bool(blob_check and blob_check.get('transcripts_pdf_blob'))
    
    return {
        "meeting_id": meeting_id,
        "pdf_ready": pdf_available,
        "transcripts_pdf_ready": transcripts_pdf_available,
        "bot_status": m.get('bot_status', 'UNKNOWN'),
        "last_updated": m.get('updated_at'),
        "message": "PDFs are ready!" if (pdf_available or transcripts_pdf_available) else "Generating PDFs..."
    }


# ============================================================
# INTEGRATIONS
# ============================================================

@app.get("/integrations", response_class=HTMLResponse)
async def integrations_page_spa(request: Request):
    if not get_current_user(request):
        return RedirectResponse("/login")
    return FileResponse(os.path.join(BASE_DIR, "v3-frontend", "index.html"))

# ============================================================
# ADD LIVE MEETING
# ============================================================

@app.get("/live", response_class=HTMLResponse)
async def live_page_spa(request: Request):
    if not get_current_user(request):
        return RedirectResponse("/login")
    return FileResponse(os.path.join(BASE_DIR, "v3-frontend", "index.html"))

@app.post("/live/join", response_class=JSONResponse)
async def live_join(request: Request, meeting_url: str = Form(...)):
    user = require_user(request)

    # --- Normalize URL: add https:// if missing (e.g. user pastes "meet.google.com/xxx") ---
    meeting_url = meeting_url.strip()
    if meeting_url and not meeting_url.startswith("http://") and not meeting_url.startswith("https://"):
        meeting_url = "https://" + meeting_url

    # We create a 'JOIN_PENDING' meeting entry that the local pilot will pick up.
    m_id = f"join_{int(time.time())}"
    db.exec_commit('''
        INSERT INTO meetings (meeting_id, title, start_time, meet_url, user_email, bot_status, bot_status_note)
        VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?, 'JOIN_PENDING', 'Waiting for local bot pilot...')
    ''', (m_id, "Live Meeting", meeting_url, user['email']))
    return {"success": True, "message": "Renata has been alerted. Make sure your local pilot script is running!", "meeting_id": m_id}

@app.post("/live/cancel", response_class=JSONResponse)
async def live_cancel(request: Request, meeting_id: str = Form(...)):
    user = require_user(request)
    # Attempt to delete if it's still pending (bot hasn't picked it up yet)
    success, _ = db.exec_commit("DELETE FROM meetings WHERE meeting_id = ? AND user_email = ? AND bot_status = 'JOIN_PENDING'", (meeting_id, user['email']))
    
    # If the bot already picked it up, set to CANCELED so it might abort.
    db.exec_commit("UPDATE meetings SET bot_status = 'CANCELED', bot_status_note = 'Canceled by user' WHERE meeting_id = ? AND user_email = ?", (meeting_id, user['email']))
    return {"success": True, "message": "Dispatch canceled successfully."}

@app.post("/api/profile/save", response_class=JSONResponse)
async def settings_api_save(request: Request):
    user = require_user(request)
    data = await request.json()
    print(f">>> SAVING SETTINGS FOR {user['email']}: {data}")
    
    settings = {}
    if "name" in data: settings["name"] = data["name"]
    if "bot_name" in data: settings["bot_name"] = data["bot_name"]
    if "auto_join" in data: settings["bot_auto_join"] = 1 if data["auto_join"] else 0
    if "recording" in data: settings["bot_recording_enabled"] = 1 if data["recording"] else 0
    
    if settings:
        try:
            db.update_user_profile(user["email"], settings)
            print(f">>> SETTINGS UPDATED IN DB.")
        except Exception as e:
            print(f">>> DB UPDATE FAILED: {e}")
            return {"success": False, "error": str(e)}
        
    # Update local session for UI consistency if name changed
    if "name" in data and "user" in request.session:
        request.session["user"]["name"] = data["name"]
        
    return {"success": True}

@app.post("/upgrade_account", response_class=JSONResponse)
async def upgrade_account(request: Request):
    user = require_user(request)
    try:
        db.update_user_profile(user["email"], {"subscription_plan": "Pro"})
        return {"success": True, "message": "Upgraded to Pro successfully!"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/settings", response_class=HTMLResponse)
async def settings_page_spa(request: Request):
    if not get_current_user(request):
        return RedirectResponse("/login")
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
    """
    MULTI-USER ISOLATION: Each user can ONLY download their own PDFs
    - Checks user_email before serving the file
    - PDFs are bound to the user who initiated the meeting
    - Security: Users cannot access other users' PDFs
    """
    user = get_current_user(request)
    if not user: raise HTTPException(status_code=401)
    
    # 1. Check Local Disk (for local dev)
    path = Path("meeting_outputs") / filename
    if path.exists():
        return FileResponse(path, media_type="application/pdf", filename=filename)
        
    # 2. Check Database Blob (for Cloud/Vercel)
    # Search for a meeting using this filename in the pdf_path
    # SECURITY: Only returns file if it belongs to the current user
    meeting = db.fetch_one("SELECT pdf_blob FROM meetings WHERE pdf_path LIKE ? AND user_email = ?", 
                           (f"%{filename}%", user['email']))
    
    if meeting and meeting.get('pdf_blob'):
        try:
            pdf_bytes = base64.b64decode(meeting['pdf_blob'])
            return StreamingResponse(
                io.BytesIO(pdf_bytes),
                media_type="application/pdf",
                headers={"Content-Disposition": f"inline; filename={filename}"}
            )
        except Exception as e:
            print(f"Error serving PDF from DB: {e}")
            raise HTTPException(status_code=500, detail="Error retrieving PDF from cloud storage.")
            
    raise HTTPException(status_code=404, detail="PDF Not Found. If you just finished the meeting, wait 10 seconds for the cloud sync.")

@app.get("/download/transcripts_pdf/{filename}")
async def download_transcripts_pdf(filename: str, request: Request):
    """
    MULTI-USER ISOLATION: Each user can ONLY download their own transcripts PDFs
    - Checks user_email before serving the file
    - Transcripts PDFs are bound to the user who initiated the meeting
    - Security: Users cannot access other users' transcripts
    """
    user = get_current_user(request)
    if not user: raise HTTPException(status_code=401)
    
    # 1. Check Local Disk (for local dev)
    path = Path("meeting_outputs") / filename
    if path.exists():
        return FileResponse(path, media_type="application/pdf", filename=filename)
        
    # 2. Check Database Blob (for Cloud/Vercel)
    # Strategy A: Try exact match on transcripts_pdf_path
    # SECURITY: Only returns file if it belongs to the current user
    meeting = db.fetch_one("SELECT transcripts_pdf_blob FROM meetings WHERE transcripts_pdf_path LIKE ? AND user_email = ?", 
                           (f"%{filename}%", user['email']))
    
    # Strategy B: If A fails, try to find a meeting where the main PDF matches (fallback for old or misnamed records)
    if not (meeting and meeting.get('transcripts_pdf_blob')):
        search_name = filename.replace("Transcripts_", "Report_")
        meeting = db.fetch_one("SELECT transcripts_pdf_blob FROM meetings WHERE pdf_path LIKE ? AND user_email = ?",
                               (f"%{search_name}%", user['email']))

    if meeting and meeting.get('transcripts_pdf_blob'):
        try:
            pdf_bytes = base64.b64decode(meeting['transcripts_pdf_blob'])
            return StreamingResponse(
                io.BytesIO(pdf_bytes),
                media_type="application/pdf",
                headers={"Content-Disposition": f"inline; filename={filename}"}
            )
        except Exception as e:
            print(f"Error serving Transcripts PDF from DB: {e}")
            raise HTTPException(status_code=500, detail="Error retrieving Transcripts PDF from cloud storage.")
            
    raise HTTPException(status_code=404, detail="Transcripts PDF Not Found.")

@app.get("/download/json/{filename}")
async def download_json(filename: str, request: Request):
    user = get_current_user(request)
    if not user: raise HTTPException(status_code=401)
    path = Path("meeting_outputs") / filename
    if not path.exists(): raise HTTPException(status_code=404)
    return FileResponse(path, media_type="application/json", filename=filename)

# Duplicate routes at the end removed.

# ============================================================

# ============================================================
# GMAIL INTELLIGENCE (Contextual Briefs)
# ============================================================

@app.get("/api/gmail_intelligence")
async def get_gmail_intelligence(request: Request):
    user = require_user(request)
    email = user['email']
    
    try:
        creds = get_user_credentials(email)
        if not creds: return {"briefs": []}

        from googleapiclient.discovery import build
        cal_svc = build("calendar", "v3", credentials=creds)
        gm_svc = build("gmail", "v1", credentials=creds)

        # 1. Fetch upcoming meetings (next 24h)
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat().replace('+00:00', 'Z')
        tomorrow = (now_dt + timedelta(days=1)).isoformat().replace('+00:00', 'Z')
        
        cal_res = cal_svc.events().list(
            calendarId='primary', timeMin=now, timeMax=tomorrow,
            singleEvents=True, orderBy='startTime'
        ).execute()
        events = cal_res.get('items', [])

        briefs = []
        for ev in events:
            m_id = ev.get('id')
            title = ev.get('summary', 'Untitled')
            
            # Check DB Cache (for this session/day)
            cached = db.fetch_all("SELECT insights FROM gmail_briefs WHERE user_email = ? AND meeting_id = ?", (email, m_id))
            if cached:
                briefs.append({
                    "meeting_id": m_id,
                    "meeting_title": title,
                    "insights": cached[0]['insights'],
                    "start_time": fmt_time(ev['start'].get('dateTime', ev['start'].get('date')))
                })
                continue

            # 2. Search Gmail
            # Very basic search for demo: just the title
            query = f'"{title}"'
            gm_res = gm_svc.users().messages().list(userId='me', q=query, maxResults=5).execute()
            messages = gm_res.get('messages', [])
            
            insights = "No previous email discussion found for this meeting."
            if messages:
                snippets = []
                for msg in messages:
                    m_data = gm_svc.users().messages().get(userId='me', id=msg['id'], format='minimal').execute()
                    snippets.append(m_data.get('snippet', ''))

                # 3. Summarize with Gemini
                context_text = "\n\n".join(snippets)
                prompt = (f"The following are snippets from previous emails related to an upcoming meeting called '{title}'. "
                         "Extract 3 main background points or pending tasks to brief the participant. Be professional and concise.\n\n"
                         f"EMAILS:\n{context_text}")
                
                api_key = os.getenv("GEMINI_API_KEY")
                if api_key:
                    try:
                        import google.generativeai as genai
                        genai.configure(api_key=api_key)
                        # Priority: 3.0 -> 2.5
                        for model_id in ["gemini-3-flash-preview", "gemini-2.5-flash-preview"]:
                            try:
                                model = genai.GenerativeModel(model_id)
                                gen_res = model.generate_content(prompt)
                                insights = gen_res.text
                                if insights: break
                            except: continue
                    except: insights = "Email context found but analysis failed."
                else:
                    insights = "Gemini Key missing - cannot analyze context."

            # Save to storage (gmail_briefs)
            db.exec_commit("INSERT INTO gmail_briefs (user_email, meeting_id, meeting_title, insights) VALUES (?, ?, ?, ?)",
                           (email, m_id, title, insights))
                
            briefs.append({
                "meeting_id": m_id,
                "meeting_title": title,
                "insights": insights,
                "start_time": fmt_time(ev['start'].get('dateTime', ev['start'].get('date')))
            })

        # 4. Fetch general recent emails (Inbox activity)
        recent_res = gm_svc.users().messages().list(userId='me', maxResults=10).execute()
        recent_msgs = recent_res.get('messages', [])
        
        inbox_emails = []
        for r_msg in recent_msgs:
            # We fetch minimal format to get headers + snippet quickly
            m_data = gm_svc.users().messages().get(userId='me', id=r_msg['id'], format='full').execute()
            headers = m_data.get('payload', {}).get('headers', [])
            
            subj = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'No Subject')
            sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), 'Unknown')
            
            inbox_emails.append({
                "id": r_msg['id'],
                "subject": subj,
                "from": sender,
                "snippet": m_data.get('snippet', '')
            })

        return {"briefs": briefs, "recent_emails": inbox_emails}

    except Exception as e:
        print(f"Gmail Intel Error: {e}")
        return {"briefs": [], "error": str(e)}

# HEALTH CHECK (Railway uses this)
# ============================================================

@app.get("/health")
async def health():
    return {"status": "ok", "service": "RENATA Meeting Intelligence", "version": "1.0.5"}

# ============================================================
# SEO / SEARCH ENGINE OPTIMIZATION
# ============================================================

@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt():
    """Standard robots.txt for Search Console."""
    return "User-agent: *\nAllow: /\nSitemap: https://meet.nexren.ai/sitemap.xml"

@app.get("/sitemap.xml")
async def sitemap_xml():
    """XML Sitemap for Google Indexing."""
    content = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://meet.nexren.ai/</loc>
    <lastmod>2026-03-30</lastmod>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>https://meet.nexren.ai/privacy</loc>
    <lastmod>2026-03-30</lastmod>
    <priority>0.8</priority>
  </url>
  <url>
    <loc>https://meet.nexren.ai/terms</loc>
    <lastmod>2026-03-30</lastmod>
    <priority>0.5</priority>
  </url>
</urlset>
"""
    return Response(content=content, media_type="application/xml")
