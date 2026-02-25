import streamlit as st
import subprocess
import os
import time
import sys
import json
import textwrap
from pathlib import Path
from datetime import datetime

# Dependency check for auto-refresh
try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:
    st.error("Missing dependency: Run 'pip install streamlit-autorefresh'")

# --- HELPER FUNCTIONS FOR ENHANCED MEETING CARDS ---
def get_meeting_status(start_time, end_time=None):
    """
    Determine meeting status based on current time.
    Returns: (status_text, status_color, status_emoji)
    """
    from datetime import datetime, timezone, timedelta
    
    now = datetime.now(timezone.utc)
    start = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
    
    # If we have end time, check if meeting is over
    if end_time:
        end = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
        if now > end:
            return ("COMPLETED", "#10b981", "")
    
    # Calculate time difference
    time_diff = (start - now).total_seconds() / 60  # in minutes
    
    if time_diff < -5:  # Started more than 5 minutes ago
        return ("IN PROGRESS", "#10b981", "")
    elif time_diff < 0:  # Started recently (within 5 min)
        return ("JUST STARTED", "#f59e0b", "")
    elif time_diff < 5:  # Starting very soon
        return ("STARTING SOON", "#f59e0b", "")
    elif time_diff < 60:  # Within next hour
        return ("UPCOMING", "#3b82f6", "")
    else:  # Later
        return ("SCHEDULED", "#6b7280", "")


def get_relative_time(start_time):
    """
    Get human-readable relative time.
    Returns: "Starts in 15 minutes" or "Started 5 minutes ago"
    """
    from datetime import datetime, timezone
    
    now = datetime.now(timezone.utc)
    start = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
    
    diff_seconds = (start - now).total_seconds()
    diff_minutes = abs(diff_seconds) / 60
    
    if diff_seconds < 0:  # Meeting already started
        if diff_minutes < 60:
            return f"Started {int(diff_minutes)} min ago"
        else:
            hours = int(diff_minutes / 60)
            return f"Started {hours}h ago"
    else:  # Meeting in future
        if diff_minutes < 60:
            return f"Starts in {int(diff_minutes)} min"
        elif diff_minutes < 1440:  # Less than 24 hours
            hours = int(diff_minutes / 60)
            return f"Starts in {hours}h"
        else:
            return start.strftime("Starts %b %d at %I:%M %p")


def get_participant_count(event):
    """
    Extract participant count from calendar event.
    Returns: (count, organizer_name)
    """
    attendees = event.get('attendees', [])
    count = len(attendees)
    
    organizer = event.get('organizer', {})
    organizer_name = organizer.get('displayName', organizer.get('email', 'Unknown'))
    
    return count, organizer_name

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Renata | Personal AI Assistant",
    layout="wide",
    page_icon="AI",
    initial_sidebar_state="expanded"
)

# AUTO-REFRESH EVERY 30 SECONDS (Replicates Read.ai's live dashboard)
st_autorefresh(interval=30000, key="datarefresh")

# --- 2. PROFESSIONAL STYLING ---
st.markdown("""
<style>
    /* Professional Typography */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    /* Main Layout */
    [data-testid="stAppViewContainer"] { 
        background: radial-gradient(circle at top right, #f8fafc, #f1f5f9);
    }
    
    /* Sidebar - Premium Deep Blue */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0f172a 0%, #1e1b4b 100%) !important;
        box-shadow: 10px 0 30px rgba(0,0,0,0.15) !important;
    }

    /* Modern Cards */
    .main-card {
        background: rgba(255, 255, 255, 0.9);
        backdrop-filter: blur(12px);
        border-radius: 20px;
        padding: 25px;
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
        border: 1px solid rgba(255, 255, 255, 0.5);
    }
    
    .bot-status-active {
        color: #10b981;
        font-weight: 800;
        animation: pulse 2s infinite;
    }
    
    @keyframes pulse {
        0% { opacity: 1; }
        50% { opacity: 0.5; }
        100% { opacity: 1; }
    }
</style>
""", unsafe_allow_html=True)

# --- HELPER: Get User Info from Token ---
def get_user_info():
    """Extract user information from Google token and sync with DB"""
    import meeting_database as db
    try:
        if os.path.exists('token.json'):
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            
            creds = Credentials.from_authorized_user_file('token.json')
            
            # Get user info from Google
            service = build('oauth2', 'v2', credentials=creds)
            google_info = service.userinfo().get().execute()
            
            email = google_info.get('email', 'Unknown')
            name = google_info.get('name', 'User')
            picture = google_info.get('picture', None)
            
            # Sync with local database to ensure persistence for settings
            db.upsert_user(email, name, picture)
            
            # Return merged profile (Local DB overrides Google for customized names/pics)
            profile = db.get_user_profile(email)
            if profile:
                return {
                    'email': profile['email'],
                    'name': profile['name'] or name,
                    'picture': profile['picture'] or picture,
                    'home_address': profile['home_address'],
                    'office_address': profile['office_address'],
                    'verified_email': True
                }
                
            return {
                'email': email,
                'name': name,
                'picture': picture,
                'verified_email': True
            }
    except Exception as e:
        print(f"Auth error: {e}")
        # If the token is invalid or expired, delete it so the user can re-auth
        if "invalid_grant" in str(e) or "expired" in str(e).lower():
            if os.path.exists('token.json'):
                try:
                    os.remove('token.json')
                    print("Expired token deleted. Please refresh the page to sign in again.")
                except: pass
        return None
    return None

# --- SIDEBAR STATUS ---
def display_bot_status_sidebar():
    import meeting_database as db
    from datetime import datetime
    
    active_meet = db.get_active_joining_meeting()
    
    if active_meet:
        status = active_meet['bot_status']
        title = active_meet['title']
        joined_at_iso = active_meet.get('bot_joined_at')
        status_note = active_meet.get('bot_status_note', '')
        
        # Calculate duration
        duration_str = ""
        if joined_at_iso:
            try:
                # Handle ISO format with potential Z or offsets
                joined_at_iso = joined_at_iso.replace('Z', '+00:00')
                joined_dt = datetime.fromisoformat(joined_at_iso)
                now = datetime.now(joined_dt.tzinfo)
                diff = now - joined_dt
                mins = int(diff.total_seconds() // 60)
                duration_str = f" • +{mins}m"
            except: pass

        if status == "JOINING":
             st.sidebar.markdown(f"""
             <div style="background: rgba(59, 130, 246, 0.1); border: 1px solid #3b82f6; padding: 10px; border-radius: 8px; margin-bottom: 20px;">
                <div style="color: #3b82f6; font-weight: bold; font-size: 0.8rem; display: flex; align-items: center;">
                    <span style="height: 8px; width: 8px; background-color: #3b82f6; border-radius: 50%; display: inline-block; margin-right: 8px; animation: pulse 1s infinite;"></span>
                    Renata: JOINING...
                </div>
                <div style="font-size: 0.75rem; margin-top: 4px; color: #333;">{title}</div>
                {f'<div style="font-size: 0.7rem; margin-top: 4px; color: #64748b; font-style: italic;">{status_note}</div>' if status_note else ''}
             </div>
             """, unsafe_allow_html=True)
        
        elif status == "CONNECTED":
             st.sidebar.markdown(f"""
             <div style="background: rgba(16, 185, 129, 0.1); border: 1px solid #10b981; padding: 10px; border-radius: 8px; margin-bottom: 20px;">
                <div style="color: #10b981; font-weight: bold; font-size: 0.8rem; display: flex; align-items: center;">
                    <span style="height: 8px; width: 8px; background-color: #10b981; border-radius: 50%; display: inline-block; margin-right: 8px;"></span>
                    Renata: CONNECTED
                </div>
                <div style="font-size: 0.75rem; margin-top: 4px; color: #333;">{title}{duration_str}</div>
                {f'<div style="font-size: 0.7rem; margin-top: 4px; color: #64748b; font-style: italic;">{status_note}</div>' if status_note else ''}
             </div>
             """, unsafe_allow_html=True)
        
        elif status == "PROCESSING":
             st.sidebar.markdown(f"""
             <div style="background: rgba(245, 158, 11, 0.1); border: 1px solid #f59e0b; padding: 10px; border-radius: 8px; margin-bottom: 20px;">
                <div style="color: #f59e0b; font-weight: bold; font-size: 0.8rem; display: flex; align-items: center;">
                    <span style="height: 8px; width: 8px; background-color: #f59e0b; border-radius: 50%; display: inline-block; margin-right: 8px; animation: pulse 1s infinite;"></span>
                    Renata: PROCESSING
                </div>
                <div style="font-size: 0.75rem; margin-top: 4px; color: #333;">{title}</div>
                {f'<div style="font-size: 0.7rem; margin-top: 4px; color: #64748b; font-style: italic;">{status_note}</div>' if status_note else ''}
             </div>
             """, unsafe_allow_html=True)
        
        elif status == "COMPLETED":
             st.sidebar.markdown(f"""
             <div style="background: rgba(16, 185, 129, 0.1); border: 1px solid #10b981; padding: 10px; border-radius: 8px; margin-bottom: 20px;">
                <div style="color: #10b981; font-weight: bold; font-size: 0.8rem; display: flex; align-items: center;">
                    <span style="height: 8px; width: 8px; background-color: #10b981; border-radius: 50%; display: inline-block; margin-right: 8px;"></span>
                    Renata: COMPLETED
                </div>
                <div style="font-size: 0.75rem; margin-top: 4px; color: #333;">{title}</div>
                {f'<div style="font-size: 0.7rem; margin-top: 4px; color: #64748b; font-style: italic;">{status_note}</div>' if status_note else ''}
             </div>
             """, unsafe_allow_html=True)
        
        else:  # IDLE or other
             st.sidebar.markdown(f"""
             <div style="background: rgba(100, 116, 139, 0.1); border: 1px dashed #94a3b8; padding: 10px; border-radius: 8px; margin-bottom: 20px;">
                <div style="color: #64748b; font-weight: bold; font-size: 0.8rem; display: flex; align-items: center;">
                    <span style="height: 8px; width: 8px; background-color: #94a3b8; border-radius: 50%; display: inline-block; margin-right: 8px;"></span>
                    Renata: IDLE
                </div>
                <div style="font-size: 0.75rem; margin-top: 4px; color: #64748b;">Ready to join</div>
             </div>
             """, unsafe_allow_html=True)
    else:
        st.sidebar.markdown(f"""
         <div style="background: rgba(100, 116, 139, 0.1); border: 1px dashed #94a3b8; padding: 10px; border-radius: 8px; margin-bottom: 20px;">
            <div style="color: #64748b; font-weight: bold; font-size: 0.8rem; display: flex; align-items: center;">
                <span style="height: 8px; width: 8px; background-color: #94a3b8; border-radius: 50%; display: inline-block; margin-right: 8px;"></span>
                Renata: IDLE
            </div>
            <div style="font-size: 0.75rem; margin-top: 4px; color: #64748b;">Ready to join</div>
         </div>
         """, unsafe_allow_html=True)

# --- SIDEBAR CALL ---
display_bot_status_sidebar()

# --- 3. AUTHENTICATION GATE ---
if not os.path.exists("token.json"):
    # Inject global styles
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');

    html, body, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
        font-family: 'Inter', sans-serif !important;
        background: #ffffff !important;
        padding: 0 !important;
        margin: 0 !important;
    }
    [data-testid="stHeader"] { display: none !important; }
    [data-testid="stToolbar"] { display: none !important; }
    #MainMenu { display: none !important; }
    footer { display: none !important; }
    [data-testid="stSidebar"] { display: none !important; }

    /* Remove default Streamlit column padding */
    [data-testid="stHorizontalBlock"] {
        gap: 0 !important;
        padding: 0 !important;
        align-items: stretch !important;
    }
    [data-testid="column"] {
        padding: 0 !important;
    }

    /* HERO panel fills its column height */
    .hero-panel {
        background: linear-gradient(145deg, #1e1b8b 0%, #4338ca 40%, #6d28d9 75%, #7c3aed 100%);
        padding: 70px 55px;
        min-height: 100vh;
        display: flex;
        flex-direction: column;
        justify-content: center;
        position: relative;
        overflow: hidden;
    }
    .hero-panel::before {
        content: '';
        position: absolute;
        top: -80px; right: -80px;
        width: 360px; height: 360px;
        background: rgba(255,255,255,0.06);
        border-radius: 50%;
    }
    .hero-panel::after {
        content: '';
        position: absolute;
        bottom: -120px; left: -60px;
        width: 420px; height: 420px;
        background: rgba(255,255,255,0.04);
        border-radius: 50%;
    }
    .dot-grid {
        position: absolute; top: 0; right: 0; bottom: 0; left: 0;
        background-image: radial-gradient(rgba(255,255,255,0.15) 1px, transparent 1px);
        background-size: 28px 28px;
        pointer-events: none;
    }
    .hero-brand {
        display: flex; align-items: center; gap: 12px;
        margin-bottom: 55px; position: relative; z-index: 1;
    }
    .hero-brand-name {
        font-size: 1.1rem; font-weight: 700;
        color: #fff; letter-spacing: 0.5px;
    }
    .hero-headline {
        font-size: 3rem; font-weight: 900;
        color: #ffffff; line-height: 1.15;
        margin-bottom: 24px; position: relative; z-index: 1;
    }
    .hero-sub {
        font-size: 1rem; color: rgba(255,255,255,0.8);
        line-height: 1.75; max-width: 400px;
        margin-bottom: 48px; position: relative; z-index: 1;
    }
    .hero-features { display: flex; flex-direction: column; gap: 20px; position: relative; z-index: 1; }
    .hero-fi { display: flex; align-items: center; gap: 16px; }
    .hero-fi-icon {
        width: 46px; height: 46px; flex-shrink: 0;
        background: rgba(255,255,255,0.15);
        border-radius: 13px;
        display: flex; align-items: center; justify-content: center; font-size: 1.2rem;
    }
    .hero-fi-text strong { display: block; color: #fff; font-size: 0.95rem; font-weight: 700; margin-bottom: 3px; }
    .hero-fi-text span { color: rgba(255,255,255,0.65); font-size: 0.82rem; }
    .hero-stats {
        display: flex; gap: 40px; margin-top: 55px; padding-top: 30px;
        border-top: 1px solid rgba(255,255,255,0.15); position: relative; z-index: 1;
    }
    .stat-item strong { display: block; color: #fff; font-size: 1.6rem; font-weight: 800; }
    .stat-item span { color: rgba(255,255,255,0.6); font-size: 0.8rem; }

    /* RIGHT login panel */
    .login-panel {
        background: #ffffff;
        min-height: 100vh;
        display: flex; flex-direction: column;
        align-items: center; justify-content: center;
        padding: 60px 50px;
    }
    .login-card { width: 100%; max-width: 360px; }
    .login-card h2 { font-size: 1.9rem; font-weight: 800; color: #0f172a; margin: 0 0 8px 0; }
    .login-card .sub { color: #64748b; font-size: 0.95rem; margin: 0 0 36px 0; line-height: 1.6; }
    .trust-badges { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 28px; }
    .trust-badge {
        background: #f8fafc; border: 1px solid #e2e8f0;
        padding: 6px 13px; border-radius: 20px;
        font-size: 0.75rem; color: #475569; font-weight: 600;
    }
    .login-footer { margin-top: 28px; font-size: 0.75rem; color: #94a3b8; line-height: 1.7; }

    /* Style the sign-in button to span full width */
    div[data-testid="column"]:last-child .stButton > button {
        width: 100% !important;
        padding: 14px !important;
        font-size: 1rem !important;
        font-weight: 700 !important;
        border-radius: 12px !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # Two-column layout: left = hero, right = login form
    col_left, col_right = st.columns([1.1, 0.9])

    # ── LEFT: Hero Panel (pure HTML, fully self-contained) ──
    with col_left:
        st.markdown("""
        <div class="hero-panel">
            <div class="dot-grid"></div>
            <div class="hero-brand">
                <span class="hero-brand-name">Renata AI</span>
            </div>
            <div class="hero-headline">Your AI<br>Meeting<br>Assistant</div>
            <p class="hero-sub">
                Renata joins your meetings, records every word, and delivers
                intelligent summaries so you stay fully present.
            </p>
            <div class="hero-features">
                <div class="hero-fi">
                    <div class="hero-fi-text">
                        <strong>Automatic Calendar Sync</strong>
                        <span>Joins your Google Meet calls automatically</span>
                    </div>
                </div>
                <div class="hero-fi">
                    <div class="hero-fi-text">
                        <strong>Live Transcription</strong>
                        <span>Real-time speaker-attributed transcripts</span>
                    </div>
                </div>
                <div class="hero-fi">
                    <div class="hero-fi-text">
                        <strong>AI Intelligence Reports</strong>
                        <span>Summaries, action items &amp; chapter breakdowns</span>
                    </div>
                </div>
            </div>
            <div class="hero-stats">
                <div class="stat-item"><strong>100%</strong><span>Auto Capture</span></div>
                <div class="stat-item"><strong>2x</strong><span>Faster Decisions</span></div>
                <div class="stat-item"><strong>Zero</strong><span>Missed Items</span></div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # ── RIGHT: Login Panel ──
    with col_right:
        # Top spacer to vertically center content
        st.markdown("""
        <style>
        /* Push Streamlit content to center vertically in the right column */
        div[data-testid="column"]:last-child > div:first-child {
            display: flex;
            flex-direction: column;
            justify-content: center;
            min-height: 100vh;
            padding: 0 50px;
        }
        .welcome-icon {
            width: 64px; height: 64px;
            background: linear-gradient(135deg, #4338ca, #7c3aed);
            border-radius: 18px;
            display: flex; align-items: center; justify-content: center;
            font-size: 1.8rem;
            margin-bottom: 24px;
            box-shadow: 0 8px 24px rgba(99, 58, 237, 0.25);
        }
        .welcome-label {
            font-size: 0.8rem;
            font-weight: 700;
            letter-spacing: 2px;
            text-transform: uppercase;
            background: linear-gradient(90deg, #4338ca, #7c3aed);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: 10px;
        }
        .welcome-heading {
            font-size: 2.4rem;
            font-weight: 900;
            color: #0f172a;
            line-height: 1.2;
            margin-bottom: 12px;
        }
        .welcome-heading span {
            background: linear-gradient(90deg, #4338ca, #7c3aed);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        .welcome-sub {
            color: #64748b;
            font-size: 0.95rem;
            line-height: 1.65;
            margin-bottom: 32px;
        }
        .welcome-divider {
            height: 1px;
            background: linear-gradient(90deg, #e2e8f0, transparent);
            margin-bottom: 28px;
        }
        </style>

        <div style="max-width: 360px; margin: 0 auto; padding-top: 30vh;">
            <div class="welcome-label">Renata AI Platform</div>
            <div class="welcome-heading">Welcome<br>Back</div>
            <p class="welcome-sub">
                Sign in to access your meetings,<br>
                transcripts and AI reports.
            </p>
            <div class="welcome-divider"></div>
        </div>
        """, unsafe_allow_html=True)

        # Sign-in button
        _, btn_col, _ = st.columns([0.08, 0.84, 0.08])
        with btn_col:
            if st.button("🔐 Sign in with Google", use_container_width=True, type="primary"):
                with st.spinner("Connecting to Google Auth..."):
                    import renata_bot_pilot
                    result = renata_bot_pilot.run_gmail_registration()
                    if result == "success":
                        st.success("Welcome! Unlocking your workspace...")
                        st.rerun()
                    else:
                        st.error(f"SignIn Failed: {result}")

        st.markdown("""
        <div style="max-width: 360px; margin: 20px auto 0 auto;">
            <div class="trust-badges">
                <span class="trust-badge">🔒 Google OAuth 2.0</span>
                <span class="trust-badge">🛡️ SOC 2 Ready</span>
                <span class="trust-badge">✅ GDPR Compliant</span>
            </div>
            <p class="login-footer">
                By signing in, you agree to our Terms of Service.<br>
                Renata AI v2.2 &nbsp;|&nbsp; Secure Enterprise Intelligence
            </p>
        </div>
        """, unsafe_allow_html=True)


    st.stop()

else:
    # Get user information
    user_info = get_user_info()
    
    # --- AUTO-START Renata ENGINE (SILENT) ---
    if "engine_started" not in st.session_state:
        try:
            # Proactive Cleanup: Kill any old bot instances
            if os.name == 'nt':
                subprocess.run(['taskkill', '/F', '/FI', 'windowtitle eq Renata_AUTO_PILOT*', '/T'], capture_output=True)
            
            # Silent Launch (Hidden Console)
            CREATE_NO_WINDOW = 0x08000000
            subprocess.Popen(f'title Renata_AUTO_PILOT && {sys.executable} renata_bot_pilot.py --autopilot', 
                             shell=True,
                             creationflags=CREATE_NO_WINDOW if os.name == 'nt' else 0)
            st.session_state.engine_started = True
        except: pass
    
    # --- 4. THEME & IDENTITY SYNC ---
    import meeting_database as db
    profile = db.get_user_profile(user_info['email']) or {}
    
    # Apply Dynamic Theme (Midnight Elite)
    if profile.get('theme_mode') == 'Dark':
        st.markdown("""
        <style>
            [data-testid="stAppViewContainer"] { background-color: #0f172a !important; color: #f1f5f9 !important; }
            [data-testid="stHeader"] { background-color: #0f172a !important; }
            .main-card { 
                background-color: #1e293b !important; 
                color: #f1f5f9 !important; 
                border: 1px solid #334155 !important;
                box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.4) !important;
            }
            .stMarkdown, p, h1, h2, h3, h4, h5, h6, b, i, span { color: #f1f5f9 !important; }
            div[data-testid="stForm"] { background-color: #1e293b !important; border: 1px solid #334155 !important; }
            .stTextInput>div>div>input, .stTextArea>div>div>textarea { background-color: #0f172a !important; color: #f1f5f9 !important; }
        </style>
        """, unsafe_allow_html=True)

    # --- 5. SIDEBAR WITH NAVIGATION ---
    from components.sidebar import render_sidebar
    
    # Track the active feature/page in session state
    if "active_page" not in st.session_state:
        st.session_state.active_page = "calendar"
        # First-time user onboarding trigger
        st.session_state.show_onboarding = True
        
    page = render_sidebar(user_info, current_page=st.session_state.active_page)
    st.session_state.active_page = page

    # --- 6. ONBOARDING OVERLAY ---
    if st.session_state.get('show_onboarding'):
        with st.container():
            st.markdown("""
                <div style="background: white; border-radius: 24px; padding: 40px; border: 1px solid #e2e8f0; margin-bottom: 40px; box-shadow: 0 20px 50px rgba(0,0,0,0.1);">
                    <h2 style="margin-top:0;">Welcome to Renata AI Assistant</h2>
                    <p style="font-size: 1.1rem; color: #475569;">Let's get you set up for productive meetings in 3 simple steps.</p>
                    <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; margin: 30px 0;">
                        <div style="padding: 20px; background: #f8fafc; border-radius: 15px;">
                            <h4 style="margin: 0 0 10px 0;">Sync Calendar</h4>
                            <p style="font-size: 0.9rem; margin: 0;">Connect your Google Calendar to auto-join meetings.</p>
                        </div>
                        <div style="padding: 20px; background: #f8fafc; border-radius: 15px;">
                            <h4 style="margin: 0 0 10px 0;">Transcripts</h4>
                            <p style="font-size: 0.9rem; margin: 0;">Enjoy unlimited free transcripts for all your calls.</p>
                        </div>
                        <div style="padding: 20px; background: #f8fafc; border-radius: 15px;">
                            <h4 style="margin: 0 0 10px 0;">AI Intelligence</h4>
                            <p style="font-size: 0.9rem; margin: 0;">Unlock summaries and actions using your free credits.</p>
                        </div>
                    </div>
                </div>
            """, unsafe_allow_html=True)
            if st.button("Got it, let's go!", use_container_width=True):
                st.session_state.show_onboarding = False
                st.rerun()

    # --- 7. MAIN CONTENT AREA (FEATURE-BASED) ---
    st.markdown(f"# Renata {st.session_state.active_page.replace('_', ' ').title()}")
    
    # FEATURE: SEARCH ASSISTANT
    if st.session_state.active_page == "search_assistant":
        from rag_assistant import assistant
        import meeting_database as db
        
        # 1. Thread Management
        if 'chat_thread_id' not in st.session_state:
            st.session_state.chat_thread_id = None
        
        main_chat, history_sidebar = st.columns([3.5, 1.2])
        
        with history_sidebar:
            st.markdown("### Saved Chats")
            if st.button("New Chat", use_container_width=True, type="secondary"):
                st.session_state.chat_thread_id = None
                st.session_state.messages = []
                st.rerun()
            
            st.divider()
            past_threads = db.get_user_assistant_threads(user_info['email'])
            for t in past_threads:
                # Truncate title for button
                title = t['title'] or "New Conversation"
                if len(title) > 22: title = title[:20] + "..."
                
                # Highlight active thread
                is_active = st.session_state.chat_thread_id == t['id']
                btn_type = "primary" if is_active else "secondary"
                
                if st.button(title, key=f"th_{t['id']}", use_container_width=True, type=btn_type):
                    st.session_state.chat_thread_id = t['id']
                    st.session_state.messages = db.get_assistant_thread_messages(t['id'])
                    st.rerun()

        with main_chat:
            col1, col2, col3 = st.columns([3, 1, 1])
            with col1:
                st.warning("Quick Step: Please click Sync Knowledge to update my memory, then you can search for anything from your meetings.")
            with col2:
                if st.button("Sync Knowledge", use_container_width=True, type="primary"):
                    with st.spinner("Re-indexing meeting data..."):
                        assistant._ensure_indexed(force_reset=True)
                    st.success("Knowledge Base Synced!")
                    st.rerun()
            with col3:
                if st.button("Clear Chat", use_container_width=True):
                    st.session_state.messages = []
                    # Don't reset thread_id, just clear local list
                    st.rerun()
            
            # Chat interface
            if "messages" not in st.session_state or not st.session_state.messages:
                st.session_state.messages = [
                    {"role": "assistant", "content": "Hi! I'm Renata, and I can help you find any information from your meeting reports."}
                ]

            # Display messages
            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

            # File selector
            output_dir = os.path.join(os.getcwd(), "meeting_outputs")
            available_files = []
            if os.path.exists(output_dir):
                available_files = [f for f in os.listdir(output_dir) if f.endswith(('.pdf', '.json'))]
            
            selected_files = st.multiselect(
                "Focus on specific documents:",
                options=available_files,
                placeholder="Select reports...",
                key="doc_selector"
            )

            prompt = st.chat_input("Ask about your meetings...")
            if prompt:
                # 1. Create thread if none exists
                if st.session_state.chat_thread_id is None:
                    # Clean title from prompt
                    title = prompt[:30] + "..." if len(prompt) > 30 else prompt
                    st.session_state.chat_thread_id = db.create_assistant_thread(user_info['email'], title)
                
                # 2. Save User Message
                st.session_state.messages.append({"role": "user", "content": prompt})
                db.save_assistant_message(st.session_state.chat_thread_id, "user", prompt)
                
                with st.chat_message("user"):
                    st.markdown(prompt)

                with st.chat_message("assistant"):
                    with st.spinner("Analyzing memory..."):
                        try:
                            # Use thread_id for RAG memory too
                            answer = assistant.ask(prompt, thread_id=st.session_state.chat_thread_id, selected_files=selected_files)
                            st.markdown(answer)
                            
                            # 3. Save Assistant Message
                            st.session_state.messages.append({"role": "assistant", "content": answer})
                            db.save_assistant_message(st.session_state.chat_thread_id, "assistant", answer)
                        except Exception as e:
                            st.error(f"Error: {e}")

    # FEATURE: ANALYTICS (New)
    elif st.session_state.active_page == "analytics":
        import meeting_database as db
        import pandas as pd
        st.subheader("Meeting Engagement Analytics")
        
        stats = db.get_meeting_stats()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Meetings", stats['total_meetings'])
        c2.metric("Total Hours", stats['total_duration_hours'])
        c3.metric("Avg Participants", stats['avg_participants'])
        c4.metric("This Week", stats['meetings_this_week'])
        
        # New Row for deeper analytics
        c5, c6, c7 = st.columns(3)
        c5.metric("Avg Engagement", f"{stats.get('avg_engagement', 0)}/100")
        c6.metric("Total Words Transcribed", f"{stats.get('total_words', 0):,}")
        c7.metric("Storage Used", stats.get('storage_used', '0 MB'))
        
        st.divider()
        st.markdown("### Speaker Talk Time (Last 10 Meetings)")
        
        # Get real data from database stats
        speaker_dist = stats.get('speaker_distribution', {})
        
        if speaker_dist:
            data = {
                'Speaker': list(speaker_dist.keys()),
                'Talk Time (%)': list(speaker_dist.values())
            }
            df = pd.DataFrame(data)
            st.bar_chart(df, x='Speaker', y='Talk Time (%)')
            st.caption("Detailed per-meeting speaker analytics available in individual reports.")
        else:
            st.info("No speaker data available yet. Analytics will appear after your first recorded meeting.")

    # FEATURE: REPORTS (Screenshot 4)
    elif st.session_state.active_page == "reports":
        import meeting_database as db
        import json
        import os
        from datetime import datetime, timedelta
        
        # TOP BAR (Screenshot 4)
        col1, col2 = st.columns([3, 1])
        with col1:
            search_query = st.text_input("📁 Filter by report title or content...", placeholder="Search...")
        with col2:
            st.write("") # Spacer
            with st.popover("Upload Recording", use_container_width=True):
                st.write("Process meetings recorded outside of Renata.")
                u_file = st.file_uploader("Choose an audio file", type=["mp3", "mp4", "wav", "m4a"])
                if u_file:
                    temp_dir = Path("meeting_outputs/uploads")
                    temp_dir.mkdir(exist_ok=True, parents=True)
                    temp_path = temp_dir / u_file.name
                    with open(temp_path, "wb") as f:
                        f.write(u_file.getbuffer())
                    
                    if st.button("Start AI Analysis", use_container_width=True):
                        with st.status("Renata is analyzing your recording...", expanded=True) as status:
                            st.write("Transcribing audio...")
                            from meeting_notes_generator import AdaptiveMeetingNotesGenerator
                            generator = AdaptiveMeetingNotesGenerator()
                            
                            st.write("Extracting intelligence...")
                            generator.process(str(temp_path))
                            
                            status.update(label="Analysis Complete!", state="complete", expanded=False)
                        st.success(f"Report for '{u_file.name}' is now available in your dashboard.")
                        time.sleep(1)
                        st.rerun()

        # FILTERS (Screenshot 4)
        f_col1, f_col2, f_col3 = st.columns(3)
        with f_col1: 
            time_filter = st.selectbox("Date Filter", ["Anytime", "Today", "Yesterday", "Last 7 Days", "Last 30 Days"])
        with f_col2: 
            sort_order = st.selectbox("Sort By", ["Newest First", "Oldest First", "Title (A-Z)", "Title (Z-A)", "Size (Large to Small)"])
        with f_col3: 
            view_type = st.radio("View Type", ["Cards", "FileList"], horizontal=True)

        st.divider()
        
        # 📂 GET FILES (PDFS)
        output_dir = Path("meeting_outputs")
        pdfs = []
        if output_dir.exists():
            for f in output_dir.glob("*.pdf"):
                stats = f.stat()
                pdfs.append({
                    "name": f.name,
                    "path": str(f),
                    "size": stats.st_size,
                    "mtime": stats.st_mtime,
                    "date": datetime.fromtimestamp(stats.st_mtime)
                })

        # Apply Filters
        filtered_pdfs = pdfs
        if search_query:
            filtered_pdfs = [p for p in pdfs if search_query.lower() in p['name'].lower()]
        
        if time_filter != "Anytime":
            now = datetime.now()
            if time_filter == "Today":
                filtered_pdfs = [p for p in filtered_pdfs if p['date'].date() == now.date()]
            elif time_filter == "Yesterday":
                yesterday = now.date() - timedelta(days=1)
                filtered_pdfs = [p for p in filtered_pdfs if p['date'].date() == yesterday]
            elif time_filter == "Last 7 Days":
                limit = now - timedelta(days=7)
                filtered_pdfs = [p for p in filtered_pdfs if p['date'] >= limit]
            elif time_filter == "Last 30 Days":
                limit = now - timedelta(days=30)
                filtered_pdfs = [p for p in filtered_pdfs if p['date'] >= limit]

        # Apply Sorting
        if sort_order == "Newest First":
            filtered_pdfs.sort(key=lambda x: x['mtime'], reverse=True)
        elif sort_order == "Oldest First":
            filtered_pdfs.sort(key=lambda x: x['mtime'])
        elif sort_order == "Title (A-Z)":
            filtered_pdfs.sort(key=lambda x: x['name'].lower())
        elif sort_order == "Title (Z-A)":
            filtered_pdfs.sort(key=lambda x: x['name'].lower(), reverse=True)
        elif sort_order == "Size (Large to Small)":
            filtered_pdfs.sort(key=lambda x: x['size'], reverse=True)

        if not filtered_pdfs:
            st.info("No reports found matching your criteria. Start by recording a meeting!")
        else:
            if view_type == "FileList":
                # Table style
                for p in filtered_pdfs:
                    col_icon, col_name, col_date, col_size, col_act = st.columns([0.2, 3, 1.5, 1, 1])
                    col_name.write(p['name'])
                    col_date.write(p['date'].strftime("%Y-%m-%d %H:%M"))
                    col_size.write(f"{p['size']/1024:.1f} KB")
                    with open(p['path'], "rb") as f:
                        col_act.download_button("📩", f, file_name=p['name'], key=f"dl_{p['name']}")
                    st.divider()
            else:
                # Card style
                for p in filtered_pdfs:
                    with st.container(border=True):
                        c1, c2, c3 = st.columns([0.1, 3, 1])
                        with c2:
                            st.markdown(f"**{p['name']}**")
                            st.caption(f"Created: {p['date'].strftime('%b %d, %Y %I:%M %p')} • Size: {p['size']/1024:.1f} KB")
                        with c3:
                            with open(p['path'], "rb") as f:
                                st.download_button("Download PDF", f, file_name=p['name'], use_container_width=True, key=f"dl_card_{p['name']}")
                                
        # Also show database records if they exist and are useful
        st.markdown("### Database Archive")
        meetings = db.search_meetings(search_query) if search_query else db.get_all_meetings()
        if meetings:
            for meet in meetings:
                with st.expander(f"{meet['title']} ({meet['start_time']})"):
                    st.caption(f"{meet['start_time']} • {meet['duration_minutes'] or '??'}m • {meet['organizer_name'] or 'Unknown'}")
                    
                    st.markdown("#### 📝 Summary")
                    st.markdown(meet.get('summary_text') or "*No summary available*")
                    
                    if meet.get('action_items'):
                        st.markdown("#### ✅ Action Items")
                        try:
                            items = json.loads(meet['action_items'])
                            for item in items:
                                if isinstance(item, dict):
                                    st.markdown(f"- **{item.get('task')}** ({item.get('owner')}) - *Due: {item.get('deadline')}*")
                                else: st.markdown(f"- {item}")
                        except: st.write(meet['action_items'])

                    with st.status("View Deep Intelligence", expanded=False):
                        tab_sum, tab_chap, tab_intel = st.tabs([
                            "Summary", "Chapters", "Intelligence"
                        ])
                        
                        with tab_sum:
                            st.markdown(meet.get('summary_text') or "*No summary available*")
                        
                        with tab_chap:
                            if meet.get('chapters'):
                                try:
                                    chaps = json.loads(meet['chapters'])
                                    for c in chaps:
                                        st.markdown(f"**[{c.get('start_time')}] {c.get('title')}**")
                                        st.caption(c.get('summary'))
                                except: st.write(meet['chapters'])
                            else: st.info("No chapters identified for this meeting.")
                            
                        with tab_intel:
                            # Individual analytics
                            spk_data = {}
                            if meet.get('speaker_analytics'):
                                try: spk_data = json.loads(meet['speaker_analytics'])
                                except: pass
                            
                            eng_data = {}
                            if meet.get('engagement_metrics'):
                                try: eng_data = json.loads(meet['engagement_metrics'])
                                except: pass

                            i_col1, i_col2 = st.columns(2)
                            with i_col1:
                                st.write("Speaker Distribution")
                                if spk_data:
                                    chart_data = {
                                        'Speaker': list(spk_data.keys()),
                                        'Time (%)': [v.get('percentage', 0) for v in spk_data.values()]
                                    }
                                    st.bar_chart(pd.DataFrame(chart_data), x='Speaker', y='Time (%)')
                                else:
                                    st.info("No speaker data.")
                            
                            with i_col2:
                                st.write("Engagement")
                                score = eng_data.get('score', 0)
                                st.metric("Engagement Score", f"{score}/100")
                                st.progress(score / 100)
                                
                                words = eng_data.get('total_words', 0)
                                st.write(f"Total Words: {words}")
                                
                                if spk_data:
                                    dominant = max(spk_data.items(), key=lambda x: x[1].get('percentage', 0))[0]
                                    st.write(f"Primary Speaker: {dominant}")
                                    
                                    st.write("---")
                                    st.write("**Speaker Metrics (WPM)**")
                                    for spk, v in spk_data.items():
                                        st.caption(f"{spk}: **{v.get('wpm', 0)} WPM**")

                    # Full Transcript
                    with st.expander("Full Transcript", expanded=False):
                        st.markdown(f"```\n{meet['transcript_text'] or 'No transcript available'}\n```")
                    st.divider()

    # FEATURE: INTEGRATIONS (Screenshot 2)
    elif st.session_state.active_page == "integrations":
        from integrations_service import integrations
        import meeting_database as db
        st.subheader("Supercharge Your Workflow")
        
        # Load profile for credentials
        profile = db.get_user_profile(user_info['email']) or {}
        
        st.markdown(f"""<div class="main-card">
            <b>📧 Gmail Intelligence</b> <span style="font-size:0.75rem; color:#10b981;">● Connected</span><br>
            <small>AI-powered inbox insights and meeting follow-ups</small>
        </div>""", unsafe_allow_html=True)
        if st.button("Fetch Inbox Highlights", use_container_width=True, type="primary"):
            with st.spinner("Analyzing emails..."):
                try:
                    summaries = integrations.summarize_emails()
                    if isinstance(summaries, list):
                        if not summaries:
                            st.info("No recent emails found.")
                        for s in summaries: st.info(f"{s}")
                    else: st.warning(summaries)
                except Exception as e:
                    if "insufficientPermissions" in str(e):
                        st.error("🔑 Permission Error: RENA needs access to your Gmail. Please Logout and Sign in again to grant permission.")
                    elif "403" in str(e) or "accessNotConfigured" in str(e):
                        st.error("🚫 **Action Required:** The Gmail API is not enabled in your Google Project. Visit [Google Cloud Console](https://console.cloud.google.com/apis/library/gmail.googleapis.com) and click **'Enable'** to use this feature.")
                    else:
                        st.error(f"Error fetching emails: {e}")
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        # ZOOM INTEGRATION CARD
        is_zoom_connected = "zoom_token" in profile and profile["zoom_token"]
        zoom_status = "● Connected" if is_zoom_connected else "○ Not Connected"
        zoom_color = "#10b981" if is_zoom_connected else "#6b7280"
        
        st.markdown(f"""<div class="main-card">
            <b>📹 Zoom Meetings</b> <span style="font-size:0.75rem; color:{zoom_color};">{zoom_status}</span><br>
            <small>Directly sync meetings from your Zoom account and auto-join</small>
        </div>""", unsafe_allow_html=True)
        
        if not is_zoom_connected:
            if st.button("Connect Zoom Account", use_container_width=True):
                st.info("🔗 Zoom OAuth integration is being initialized. For now, RENA can already join Zoom meetings if the links are in your Google Calendar!")
        else:
            if st.button("Refresh Zoom Meetings", use_container_width=True, type="primary"):
                with st.spinner("Syncing with Zoom..."):
                    results = integrations.fetch_zoom_meetings(profile["zoom_token"])
                    if isinstance(results, list):
                        for m in results: st.success(f"Found: {m['title']} at {m['start']}")
                    else: st.warning(results)

    # FEATURE: ADD LIVE MEETING
    elif st.session_state.active_page == "add_live":
        st.subheader("Add RENA to a Live Meeting")
        meet_url = st.text_input("Paste Google Meet or Zoom URL", placeholder="https://meet.google.com/abc-defg-hij")
        if st.button("Inject Bot Now", use_container_width=True, type="primary"):
            if "meet.google.com" in meet_url or "zoom.us" in meet_url:
                with st.spinner("Inviting RENA to the call..."):
                    import meeting_database as db
                    success, msg = db.inject_bot_now(meet_url)
                    if success: st.success(msg)
                    else: st.error(msg)
            else:
                st.warning("Please enter a valid meeting URL.")

    # FEATURE: WORKSPACE MANAGEMENT (Restored & Enhanced)
    elif st.session_state.active_page == "add_people":
        import meeting_database as db
        st.markdown("<h2 style='color: #1e293b;'>🏁 Workspace Management</h2>", unsafe_allow_html=True)
        
        tab_join, tab_create, tab_mine = st.tabs(["🚀 Join Workspace", "🏗️ Create Workspace", "�️ Your Workspaces"])
        
        with tab_join:
            st.markdown("""
                <div style='background: #f0fdf4; padding: 15px; border-radius: 10px; border-left: 4px solid #22c55e; margin-bottom: 20px;'>
                    <h5 style='margin-bottom: 8px;'>Join an existing team</h5>
                    <p style='font-size: 0.9rem; color: #166534;'>Enter the unique Workspace ID provided by your team lead to join their digital HQ.</p>
                </div>
            """, unsafe_allow_html=True)
            
            with st.form("join_ws_form"):
                join_id = st.text_input("Enter Workspace ID", placeholder="E.g. A1B2C3D4")
                confirm_email = st.text_input("Confirm Join Email", value=user_info['email'], help="Ensure this matches your account email.")
                if st.form_submit_button("Join Team"):
                    if not join_id:
                        st.warning("Please enter a Workspace ID.")
                    elif not confirm_email:
                        st.warning("Email is required to join.")
                    else:
                        success, msg = db.join_workspace(join_id, confirm_email)
                        if success:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)
        
        with tab_create:
            st.markdown("""
                <div style='background: #f0f9ff; padding: 15px; border-radius: 10px; border-left: 4px solid #0ea5e9; margin-bottom: 20px;'>
                    <h5 style='margin-bottom: 8px;'>Build your own digital HQ</h5>
                    <p style='font-size: 0.9rem; color: #0369a1;'>Create a workspace to share meeting intelligence with your entire team. You'll get a unique ID to share with others.</p>
                </div>
            """, unsafe_allow_html=True)
            
            with st.form("create_ws_form"):
                ws_name = st.text_input("Workspace Name", placeholder="Acme Corp, Design Team, etc.")
                ws_desc = st.text_area("Description (Optional)")
                if st.form_submit_button("Create Workspace"):
                    if not ws_name:
                        st.warning("Workspace name is required.")
                    else:
                        success, ws_id = db.create_workspace(ws_name, user_info['email'], ws_desc)
                        if success:
                            st.success(f"Workspace '{ws_name}' created! ID: **{ws_id}**")
                            st.info("Share this ID with your team members so they can join!")
                            st.session_state.active_workspace_id = ws_id
                            st.session_state.active_workspace_name = ws_name
                            import time
                            time.sleep(2)
                            st.rerun()
                        else:
                            st.error(f"Error: {ws_id}")

        with tab_mine:
            st.markdown("""
                <div style='background: #faf5ff; padding: 15px; border-radius: 10px; border-left: 4px solid #7c3aed; margin-bottom: 20px;'>
                    <h5 style='margin-bottom: 6px;'>Your Created & Joined Spaces</h5>
                    <p style='font-size: 0.9rem; color: #5b21b6; margin: 0;'>Click any workspace to see its members and share its ID.</p>
                </div>
            """, unsafe_allow_html=True)

            # Fetch all workspaces the user is part of
            all_workspaces = db.get_user_workspaces(user_info['email'])

            if not all_workspaces:
                st.info("You haven't created or joined any workspaces yet. Use the tabs above to get started!")
            else:
                # Track which workspace is expanded
                if 'expanded_ws_id' not in st.session_state:
                    st.session_state.expanded_ws_id = None

                for ws in all_workspaces:
                    ws_id   = ws.get('workspace_id') or ws.get('id', '')
                    ws_name = ws.get('name', 'Unnamed Workspace')
                    ws_desc = ws.get('description', '')
                    ws_role = ws.get('role', 'member')
                    role_badge = "Owner" if ws_role == 'owner' else "Member"
                    is_expanded = (st.session_state.expanded_ws_id == ws_id)

                    # Workspace card header (clickable button)
                    col_name, col_badge, col_toggle = st.columns([3, 1.2, 0.8])
                    with col_name:
                        st.markdown(f"**{ws_name}**" + (f"  \n<small style='color:#94a3b8'>{ws_desc}</small>" if ws_desc else ""), unsafe_allow_html=True)
                    with col_badge:
                        st.markdown(f"<span style='background:#ede9fe;color:#5b21b6;padding:3px 8px;border-radius:12px;font-size:0.75rem;font-weight:600'>{role_badge}</span>", unsafe_allow_html=True)
                    with col_toggle:
                        btn_label = "▲ Close" if is_expanded else "▼ Open"
                        if st.button(btn_label, key=f"ws_toggle_{ws_id}", use_container_width=True):
                            st.session_state.expanded_ws_id = None if is_expanded else ws_id
                            st.rerun()

                    # Expanded workspace detail
                    if is_expanded:
                        st.markdown(f"""
                        <div style='background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:14px 18px;margin-bottom:6px;'>
                            <div style='display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap;'>
                                <span style='font-size:0.75rem;color:#64748b;font-weight:600;'>Workspace ID:</span>
                                <code style='background:#1e1b4b;color:#a5b4fc;padding:4px 10px;border-radius:6px;font-size:0.78rem;letter-spacing:1.5px;'>{ws_id}</code>
                                <span style='font-size:0.72rem;color:#94a3b8;'>← share this with teammates</span>
                            </div>
                        """, unsafe_allow_html=True)

                        # Members list
                        members = db.get_workspace_members(ws_id)
                        if members:
                            st.markdown(f"<p style='font-size:0.85rem;font-weight:700;color:#334155;margin-bottom:8px;'>Members ({len(members)})</p>", unsafe_allow_html=True)
                            for m in members:
                                m_email = m.get('user_email', m.get('email', ''))
                                m_joined = m.get('joined_at', '')
                                st.markdown(f"""
                                <div style='display:flex;justify-content:space-between;align-items:center;padding:8px 12px;background:white;border-radius:8px;border:1px solid #f1f5f9;margin-bottom:5px;'>
                                    <span style='font-size:0.88rem;'>{m_email}</span>
                                    <span style='font-size:0.72rem;color:#94a3b8;'>Joined {m_joined}</span>
                                </div>""", unsafe_allow_html=True)
                        else:
                            st.markdown("<p style='font-size:0.85rem;color:#94a3b8;'>No members found.</p>", unsafe_allow_html=True)

                        st.markdown("</div>", unsafe_allow_html=True)

                    st.markdown("<hr style='margin:8px 0;border:none;border-top:1px solid #f1f5f9;'>", unsafe_allow_html=True)

    # FEATURE: WORKSPACE CHAT
    elif st.session_state.active_page == "workspace_chat":
        import meeting_database as db
        ws_id = st.session_state.get('active_workspace_id')
        ws_name = st.session_state.get('active_workspace_name', 'General Chat')
        
        if not ws_id:
            st.warning("Please select or create a workspace first.")
        else:
            st.subheader(f"{ws_name} Collaboration")
            
            # Chat History
            chat_container = st.container(height=500)
            with chat_container:
                messages = db.get_workspace_messages(ws_id)
                for m in messages:
                    is_me = m['sender_email'] == user_info['email']
                    align = "right" if is_me else "left"
                    bg = "#e0e7ff" if is_me else "#f1f5f9"
                    st.markdown(f"""
                    <div style='text-align: {align}; margin-bottom: 10px;'>
                        <div style='display: inline-block; background: {bg}; padding: 10px 15px; border-radius: 15px; max-width: 80%;'>
                            <small style='color: #64748b;'>{m['sender_name']} • {m['created_at']}</small><br>
                            {m['message']}
                            {f"<br><small>📎 File: {m['attachment_name']}</small>" if m['attachment_name'] else ""}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

            # Input area
            with st.container():
                with st.form("chat_form", clear_on_submit=True):
                    col_msg, col_file = st.columns([3, 1])
                    msg = col_msg.text_input("Message", placeholder="Type something...", label_visibility="collapsed")
                    att = col_file.file_uploader("Attach", label_visibility="collapsed")
                    
                    if st.form_submit_button("Send", use_container_width=True):
                        if msg or att:
                            att_path, att_name = None, None
                            if att:
                                upload_dir = Path("meeting_outputs/uploads")
                                upload_dir.mkdir(exist_ok=True)
                                att_path = str(upload_dir / att.name)
                                with open(att_path, "wb") as f:
                                    f.write(att.getbuffer())
                                att_name = att.name
                                
                            db.send_workspace_message(ws_id, user_info['email'], user_info['name'], msg, att_path, att_name)
                            st.rerun()

    elif st.session_state.active_page == "settings":
        import meeting_database as db
        st.markdown("<h2 style='color: #0f172a;'>User Settings</h2>", unsafe_allow_html=True)
        st.write("Manage your personal profile and account preferences below.")
        
        # User details from database
        profile = db.get_user_profile(user_info['email']) or {}
        
        with st.container():
            st.markdown('<div class="main-card">', unsafe_allow_html=True)
            with st.form("settings_form"):
                st.markdown("### 👤 Personal Profile")
                
                # Profile Picture Section
                col_i, col_f = st.columns([1, 4])
                with col_i:
                    if profile.get('picture'):
                        st.image(profile['picture'], width=80)
                    else:
                        st.markdown("<div style='width:80px;height:80px;background:#f1f5f9;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:2rem;'>👤</div>", unsafe_allow_html=True)
                
                with col_f:
                    uploaded_avatar = st.file_uploader("Upload New Profile Photo", type=["png", "jpg", "jpeg"])
                    if uploaded_avatar:
                        st.info("✨ New photo selected. Click 'Save Changes' to apply.")
                    else:
                        st.caption("Supported formats: PNG, JPG, JPEG")
                
                st.divider()
                
                st.markdown("**Core Identity**")
                c1, c2 = st.columns(2)
                with c1:
                    new_name = st.text_input("Display Name", value=profile.get('name') or user_info['name'])
                with c2:
                    st.text_input("Email Address (Immutable)", value=user_info['email'], disabled=True)
                
                st.divider()
                st.markdown("**Contact Locations**")
                h_addr = st.text_input("Home Address", value=profile.get('home_address') or "", placeholder="e.g., 123 Maple St, NY")
                o_addr = st.text_input("Office Address", value=profile.get('office_address') or "", placeholder="e.g., One Infinity Loop, Cupertino")
                
                st.markdown("<br>", unsafe_allow_html=True)
                if st.form_submit_button("Save Changes", use_container_width=True):
                    final_picture = profile.get('picture')
                    
                    if uploaded_avatar:
                        # Save uploaded file locally
                        avatar_dir = Path("meeting_outputs/avatars")
                        avatar_dir.mkdir(exist_ok=True, parents=True)
                        file_ext = uploaded_avatar.name.split('.')[-1]
                        avatar_path = avatar_dir / f"{user_info['email'].replace('@', '_').replace('.', '_')}_avatar.{file_ext}"
                        
                        with open(avatar_path, "wb") as f:
                            f.write(uploaded_avatar.getbuffer())
                        final_picture = str(avatar_path)
                    
                    updates = {
                        'name': new_name,
                        'picture': final_picture,
                        'home_address': h_addr,
                        'office_address': o_addr
                    }
                    if db.update_user_profile(user_info['email'], updates):
                        st.success("Profile updated successfully! Refreshing UI...")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("Failed to update profile. Please try again.")
            st.markdown('</div>', unsafe_allow_html=True)


    elif st.session_state.active_page == "add_live":
        st.subheader("Join a Live Meeting")
        st.info("How it works: Enter any Google Meet URL, and RENA will join as a guest to record and transcribe the session for you.")
        live_url = st.text_input("Enter the Meeting URL (Google Meet, Zoom, etc.)", placeholder="https://meet.google.com/abc-defg-hij")
        
        if st.button("Join & Record Now", use_container_width=True):
            if not live_url:
                st.warning("Please provide a meeting URL.")
            else:
                import meeting_database as db
                success, msg = db.inject_bot_now(live_url)
                if success:
                    st.success("RENA is on the way! The bot will join and start recording in a few seconds.")
                else:
                    st.error(f"Failed to join meeting: {msg}")

    # DEFAULT: CALENDAR (Dashboard)
    else:
        # --- GMAIL INTELLIGENCE DASHBOARD ---
        from gmail_scanner_service import gmail_scanner
        intel = gmail_scanner.get_latest_intelligence(user_info['email'])
        
        if intel:
            st.markdown("""
                <div style="background: white; border-radius: 20px; padding: 25px; box-shadow: 0 4px 20px rgba(0,0,0,0.05); border: 1px solid #e2e8f0; margin-bottom: 30px;">
                    <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 15px;">
                        <h3 style="margin: 0; color: #0f172a;">Renata Intelligence Hub</h3>
                    </div>
                    <p style="color: #64748b; font-size: 0.95rem;">I've detected the following action points from your Gmail inbox:</p>
                </div>
            """, unsafe_allow_html=True)
            
            cols = st.columns(len(intel[:3]))
            for idx, item in enumerate(intel[:3]):
                with cols[idx]:
                    emoji = "📅" if item['category'] == 'deadline' else "🚀" if item['category'] == 'project' else "✅"
                    st.markdown(f"""
                        <div class="main-card" style="height: 180px;">
                            <div style="display: flex; justify-content: space-between;">
                                <span style="font-size: 1.2rem;">{emoji}</span>
                                <span style="font-size: 0.7rem; font-weight: 800; color: #3b82f6; text-transform: uppercase;">{item['category']}</span>
                            </div>
                            <div style="font-weight: 700; font-size: 0.9rem; margin: 10px 0;">{item['subject'][:40]}</div>
                            <div style="font-size: 0.8rem; color: #64748b;">{item['snippet'][:80]}...</div>
                        </div>
                    """, unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)

        tab1, tab2 = st.tabs(["📅 Upcoming Sessions", "📅 Smart Scheduler"])
        with tab1:
            col_main, col_stat = st.columns([2, 1])
            with col_main:
                st.subheader("📅 Today's Schedule")
                import renata_bot_pilot
                import meeting_database as db
                events = renata_bot_pilot.get_upcoming_events(max_results=10)
                if not events:
                    st.info("No more meetings scheduled for today.")
                else:
                    for event in events:
                        meet_id = event['id']
                        start_time = event['start'].get('dateTime', event['start'].get('date'))
                        db_meet = db.get_meeting(meet_id)
                        is_skipped = db_meet.get('is_skipped', 0) if db_meet else 0
                        
                        with st.container():
                            st.markdown(f"**{event.get('summary')}**")
                            c_time, c_stat = st.columns([2, 1])
                            with c_time:
                                st.caption(f"🕒 {event.get('start', {}).get('dateTime', 'All Day')}")
                            
                            with c_stat:
                                bot_stat = db_meet.get('bot_status', 'IDLE') if db_meet else 'IDLE'
                                
                                if is_skipped:
                                    st.markdown("<span style='color: #ef4444; font-size: 0.7rem; font-weight: 800;'>Status: AUTO-JOIN: OFF</span>", unsafe_allow_html=True)
                                    if st.button("Rejoin", key=f"en_{meet_id}", use_container_width=True):
                                        db.toggle_meeting_skip(meet_id, False, title=event.get('summary'), start_time=start_time)
                                        st.rerun()
                                else:
                                    # Show special status if bot is active
                                    if bot_stat == "JOINING":
                                        st.markdown("<div class='bot-status-active' style='font-size: 0.7rem;'>Renata: JOINING...</div>", unsafe_allow_html=True)
                                    elif bot_stat == "CONNECTED":
                                        st.markdown("<div style='color: #10b981; font-size: 0.7rem; font-weight: 800;'>Renata: CONNECTED</div>", unsafe_allow_html=True)
                                    else:
                                        st.markdown("<span style='color: #10b981; font-size: 0.7rem; font-weight: 800;'>Status: AUTO-JOIN: ON</span>", unsafe_allow_html=True)
                                    
                                    if st.button("Cancel Auto Join", key=f"can_{meet_id}", use_container_width=True):
                                        db.toggle_meeting_skip(meet_id, True, title=event.get('summary'), start_time=start_time)
                                        st.rerun()
                            st.divider()
            with col_stat:
                st.subheader("Quick Access")
                
                # --- INSTANT JOIN ---
                with st.expander("Instant Join", expanded=True):
                    inst_url = st.text_input("Meeting Link", placeholder="meet.google.com/...", label_visibility="collapsed")
                    if st.button("Join Now", use_container_width=True, type="primary"):
                        if inst_url:
                            # Silent background launch
                            CREATE_NO_WINDOW = 0x08000000
                            subprocess.Popen(f'title Renata_INSTANT_JOIN && {sys.executable} renata_bot_pilot.py --url "{inst_url}"', 
                                             shell=True,
                                             creationflags=CREATE_NO_WINDOW if os.name == 'nt' else 0)
                            st.toast(f"Renata is joining {inst_url}...")
                        else:
                            st.warning("Please enter a link.")

                if st.button("🔗 My Scheduling Link", use_container_width=True):
                    st.session_state.active_page = "scheduler"
                    st.rerun()
                
                with st.expander("➕ Create New Meeting", expanded=bool(st.session_state.get('last_created_meeting'))):
                    m_type = st.radio("Meeting Type", ["💨 Instant (Start Now)", "📅 Schedule for Later"], horizontal=True)
                    m_title = st.text_input("Meeting Title", placeholder="Project Sync, Interview, etc.", key="m_title_input")
                    
                    m_date = datetime.now()
                    m_time = datetime.now().time()
                    if m_type == "📅 Schedule for Later":
                        col_d, col_t = st.columns(2)
                        with col_d: m_date = st.date_input("Date")
                        with col_t: m_time = st.time_input("Time")
                    
                    m_duration = 120 # Default to 2 hours for flexibility, as requested
                    
                    if st.button("Confirm & Create", use_container_width=True):
                        if not m_title:
                            st.warning("Please enter a meeting title.")
                        else:
                            import renata_bot_pilot
                            start_dt = datetime.combine(m_date, m_time)
                            start_iso = start_dt.isoformat() + "Z"
                            
                            with st.spinner("Syncing with Google Calendar..."):
                                meet_link, status = renata_bot_pilot.create_google_meeting(m_title, start_iso, m_duration)
                                
                                if meet_link:
                                    st.session_state.last_created_meeting = {
                                        "title": m_title,
                                        "link": meet_link,
                                        "type": m_type
                                    }
                                    
                                    # Proactive Injection: Join the bot immediately for instant meetings
                                    import meeting_database as db
                                    if m_type == "💨 Instant (Start Now)":
                                        db.inject_bot_now(meet_link)
                                        st.success(f"Meeting Created & Renata is joining: {m_title}")
                                    else:
                                        st.success(f"Successfully Created: {m_title}")
                                    
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    if "accessNotConfigured" in str(status) or "403" in str(status):
                                        st.error("🚫 **Action Required:** The Google Calendar API is not enabled in your project. Visit [this link](https://console.cloud.google.com/apis/library/calendar.googleapis.com) and click **'Enable'** to allow meeting creation.")
                                    else:
                                        st.error(f"Meeting Creation Failed: {status}")
                    
                    # If a meeting was just created, show action buttons below the form
                    if st.session_state.get('last_created_meeting'):
                        m = st.session_state.last_created_meeting
                        st.markdown(f"---")
                        st.markdown(f"🔗 **Link:** [{m['link']}]({m['link']})")
                        
                        col_a, col_b = st.columns(2)
                        with col_a:
                            if st.button("Join & Record Now", key="join_now_btn", use_container_width=True):
                                import meeting_database as db
                                db.inject_bot_now(m['link'])
                                st.toast("Bot is joining the meeting...")
                        with col_b:
                            if st.button("Done", key="clear_create", use_container_width=True):
                                st.session_state.last_created_meeting = None
                                st.rerun()
        
        with tab2:
            st.subheader("🔗 Smart Scheduler Settings")
            st.markdown("""
            <div class="main-card">
                <h4>Your Scheduling Link is ACTIVE</h4>
                <p>Anyone with this link can book a meeting with you based on your Google Calendar availability.</p>
            </div>
            """, unsafe_allow_html=True)
            
            s_link = f"https://renata.ai/schedule/{user_info['email']}/active"
            st.code(s_link, language="text")
            if st.button("📋 Copy My link", use_container_width=True):
                import pyperclip
                pyperclip.copy(s_link)
                st.success("Link copied to clipboard!")
            
            st.divider()
            st.info("💡 **Tip:** Embed this link in your email signature to automate your meeting bookings.")

# --- 6. FOOTER ---
st.markdown("---")
st.caption("Renata AI v2.2 | Full Automation Enbaled | Feature Parity: ACTIVE")
