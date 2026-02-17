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
            return ("COMPLETED", "#10b981", "✅")
    
    # Calculate time difference
    time_diff = (start - now).total_seconds() / 60  # in minutes
    
    if time_diff < -5:  # Started more than 5 minutes ago
        return ("IN PROGRESS", "#10b981", "🟢")
    elif time_diff < 0:  # Started recently (within 5 min)
        return ("JUST STARTED", "#f59e0b", "🟡")
    elif time_diff < 5:  # Starting very soon
        return ("STARTING SOON", "#f59e0b", "🟡")
    elif time_diff < 60:  # Within next hour
        return ("UPCOMING", "#3b82f6", "🔵")
    else:  # Later
        return ("SCHEDULED", "#6b7280", "⚪")


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
    page_title="RENA | Enterprise AI Assistant",
    layout="wide",
    page_icon="🤖",
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
        return {
            'email': 'user@gmail.com',
            'name': 'RENA User',
            'picture': None,
            'verified_email': True
        }
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
                    RENA: JOINING...
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
                    RENA: CONNECTED
                </div>
                <div style="font-size: 0.75rem; margin-top: 4px; color: #333;">{title}{duration_str}</div>
                {f'<div style="font-size: 0.7rem; margin-top: 4px; color: #64748b; font-style: italic;">💡 {status_note}</div>' if status_note else ''}
             </div>
             """, unsafe_allow_html=True)
        
        elif status == "PROCESSING":
             st.sidebar.markdown(f"""
             <div style="background: rgba(245, 158, 11, 0.1); border: 1px solid #f59e0b; padding: 10px; border-radius: 8px; margin-bottom: 20px;">
                <div style="color: #f59e0b; font-weight: bold; font-size: 0.8rem; display: flex; align-items: center;">
                    <span style="height: 8px; width: 8px; background-color: #f59e0b; border-radius: 50%; display: inline-block; margin-right: 8px; animation: pulse 1s infinite;"></span>
                    RENA: PROCESSING
                </div>
                <div style="font-size: 0.75rem; margin-top: 4px; color: #333;">{title}</div>
                {f'<div style="font-size: 0.7rem; margin-top: 4px; color: #64748b; font-style: italic;">⚙️ {status_note}</div>' if status_note else ''}
             </div>
             """, unsafe_allow_html=True)
        
        elif status == "COMPLETED":
             st.sidebar.markdown(f"""
             <div style="background: rgba(16, 185, 129, 0.1); border: 1px solid #10b981; padding: 10px; border-radius: 8px; margin-bottom: 20px;">
                <div style="color: #10b981; font-weight: bold; font-size: 0.8rem; display: flex; align-items: center;">
                    <span style="height: 8px; width: 8px; background-color: #10b981; border-radius: 50%; display: inline-block; margin-right: 8px;"></span>
                    RENA: COMPLETED
                </div>
                <div style="font-size: 0.75rem; margin-top: 4px; color: #333;">{title}</div>
                {f'<div style="font-size: 0.7rem; margin-top: 4px; color: #64748b; font-style: italic;">✅ {status_note}</div>' if status_note else ''}
             </div>
             """, unsafe_allow_html=True)
        
        else:  # IDLE or other
             st.sidebar.markdown(f"""
             <div style="background: rgba(100, 116, 139, 0.1); border: 1px dashed #94a3b8; padding: 10px; border-radius: 8px; margin-bottom: 20px;">
                <div style="color: #64748b; font-weight: bold; font-size: 0.8rem; display: flex; align-items: center;">
                    <span style="height: 8px; width: 8px; background-color: #94a3b8; border-radius: 50%; display: inline-block; margin-right: 8px;"></span>
                    RENA: IDLE
                </div>
                <div style="font-size: 0.75rem; margin-top: 4px; color: #64748b;">Ready to join</div>
             </div>
             """, unsafe_allow_html=True)
    else:
        st.sidebar.markdown(f"""
         <div style="background: rgba(100, 116, 139, 0.1); border: 1px dashed #94a3b8; padding: 10px; border-radius: 8px; margin-bottom: 20px;">
            <div style="color: #64748b; font-weight: bold; font-size: 0.8rem; display: flex; align-items: center;">
                <span style="height: 8px; width: 8px; background-color: #94a3b8; border-radius: 50%; display: inline-block; margin-right: 8px;"></span>
                RENA: IDLE
            </div>
            <div style="font-size: 0.75rem; margin-top: 4px; color: #64748b;">Ready to join</div>
         </div>
         """, unsafe_allow_html=True)

# --- SIDEBAR CALL ---
display_bot_status_sidebar()

# --- 3. AUTHENTICATION GATE ---
if not os.path.exists("token.json"):
    # Premium RENA Portal Sign-In
    st.markdown("""
    <style>
    [data-testid="stAppViewContainer"] {
        background: #f0f9ff !important;
    }
    .signin-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 50px 20px;
    }
    .signin-card {
        background: white;
        padding: 50px;
        border-radius: 24px;
        box-shadow: 0 20px 50px rgba(15, 23, 42, 0.08);
        max-width: 480px;
        width: 100%;
        text-align: center;
        border: 1px solid #e2e8f0;
    }
    .brand-logo { 
        font-size: 4rem; margin-bottom: 20px; 
    }
    .welcome-title {
        font-size: 2.2rem;
        font-weight: 800;
        color: #0f172a;
        margin-bottom: 8px;
    }
    .punchline {
        color: #334155;
        font-size: 1.1rem;
        font-weight: 500;
        line-height: 1.6;
        margin-bottom: 30px;
    }
    .feature-highlights {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 12px;
        margin-top: 35px;
        text-align: left;
    }
    .feature-tag {
        background: #f1f5f9;
        padding: 10px 12px;
        border-radius: 10px;
        font-size: 0.8rem;
        font-weight: 600;
        color: #475569;
        display: flex;
        align-items: center;
        gap: 6px;
    }
    </style>
    
    <div class="signin-container">
        <div class="signin-card">
            <div class="brand-logo">🤖</div>
            <h1 class="welcome-title">Welcome to RENA</h1>
            <p class="punchline">
                Your intelligent meeting assistant.<br>
                <span style="color: #0ea5e9;"><b>Do meeting with ease.</b></span><br>
                Focus on the conversation, let RENA handle the notes.
            </p>
            <p style="color: #64748b; font-size: 0.9rem; margin-top: 20px;">Sign in to continue to your dashboard</p>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("🔐 Sign in with Google", use_container_width=True, type="primary"):
            with st.spinner("Connecting to Google Auth..."):
                import rena_bot_pilot
                result = rena_bot_pilot.run_gmail_registration()
                if result == "success":
                    st.success("✅ Welcome! Unlocking your workspace...")
                    st.rerun()
                else:
                    st.error(f"SignIn Failed: {result}")
    
    st.markdown("""
            <div class="feature-highlights">
                <div class="feature-tag">📅 Calendar Sync</div>
                <div class="feature-tag">🎤 Auto-Recording</div>
                <div class="feature-tag">✍️ Smart Summaries</div>
                <div class="feature-tag">📊 Group Insights</div>
            </div>
            <p style="font-size: 0.7rem; color: #94a3b8; margin-top: 30px; text-align: center;">
                RENA AI v2.1 | Secure Enterprise Intelligence<br>
                🔒 Protected by Google OAuth 2.0
            </p>
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

else:
    # Get user information
    user_info = get_user_info()
    
    # --- AUTO-START RENA ENGINE (SILENT) ---
    if "engine_started" not in st.session_state:
        try:
            # Proactive Cleanup: Kill any old bot instances
            if os.name == 'nt':
                subprocess.run(['taskkill', '/F', '/FI', 'windowtitle eq RENA_AUTO_PILOT*', '/T'], capture_output=True)
            
            # Silent Launch (Hidden Console)
            CREATE_NO_WINDOW = 0x08000000
            subprocess.Popen(f'title RENA_AUTO_PILOT && {sys.executable} rena_bot_pilot.py --autopilot', 
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
                    <h2 style="margin-top:0;">🚀 Welcome to RENA AI Assistant</h2>
                    <p style="font-size: 1.1rem; color: #475569;">Let's get you set up for productive meetings in 3 simple steps.</p>
                    <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; margin: 30px 0;">
                        <div style="padding: 20px; background: #f8fafc; border-radius: 15px;">
                            <h4 style="margin: 0 0 10px 0;">📅 Sync Calendar</h4>
                            <p style="font-size: 0.9rem; margin: 0;">Connect your Google Calendar to auto-join meetings.</p>
                        </div>
                        <div style="padding: 20px; background: #f8fafc; border-radius: 15px;">
                            <h4 style="margin: 0 0 10px 0;">📂 Transcripts</h4>
                            <p style="font-size: 0.9rem; margin: 0;">Enjoy unlimited free transcripts for all your calls.</p>
                        </div>
                        <div style="padding: 20px; background: #f8fafc; border-radius: 15px;">
                            <h4 style="margin: 0 0 10px 0;">✨ AI Intelligence</h4>
                            <p style="font-size: 0.9rem; margin: 0;">Unlock summaries and actions using your free credits.</p>
                        </div>
                    </div>
                </div>
            """, unsafe_allow_html=True)
            if st.button("Got it, let's go! 🏁", use_container_width=True):
                st.session_state.show_onboarding = False
                st.rerun()

    # --- 7. MAIN CONTENT AREA (FEATURE-BASED) ---
    st.markdown(f"## 🤖 RENA {st.session_state.active_page.replace('_', ' ').title()}")
    
    # FEATURE: SEARCH ASSISTANT
    if st.session_state.active_page == "search_assistant":
        from search_copilot_service import assistant
        
        col1, col2 = st.columns([4, 1])
        with col1:
            st.info("💡 **Assistant Tip:** Ask about specific dates, people, or action items from past meetings.")
        with col2:
            if st.button("🗑️ Clear Chat", use_container_width=True):
                st.session_state.messages = []
                st.rerun()
        
        # Chat interface
        if "messages" not in st.session_state:
            st.session_state.messages = [
                {"role": "assistant", "content": "Hello! I'm your Search Assistant. I can analyze all your past transcripts and answer regular questions too. What would you like to know?"}
            ]

        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        prompt = st.chat_input("Ask about your meetings...")
        if prompt:
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                with st.spinner("Analyzing your data..."):
                    try:
                        # Call the actual RAG service
                        answer = assistant.ask(prompt)
                        st.markdown(answer)
                        st.session_state.messages.append({"role": "assistant", "content": answer})
                    except Exception as e:
                        st.error(f"Error connecting to Search Assistant: {e}")

    # FEATURE: ANALYTICS (New)
    elif st.session_state.active_page == "analytics":
        import meeting_database as db
        import pandas as pd
        st.subheader("📊 Meeting Engagement Analytics")
        
        stats = db.get_meeting_stats()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Meetings", stats['total_meetings'])
        c2.metric("Total Hours", stats['total_duration_hours'])
        c3.metric("Avg Participants", stats['avg_participants'])
        c4.metric("This Week", stats['meetings_this_week'])
        
        st.divider()
        st.markdown("### 🗣️ Speaker Talk Time (Last 10 Meetings)")
        # Mocking data for visualization based on common participants
        data = {
            'Speaker': ['User', 'John Doe', 'Sarah Miller', 'Others'],
            'Talk Time (%)': [45, 25, 20, 10]
        }
        df = pd.DataFrame(data)
        st.bar_chart(df, x='Speaker', y='Talk Time (%)')
        st.caption("Detailed per-meeting speaker analytics available in individual reports.")

    # FEATURE: REPORTS (Screenshot 4)
    elif st.session_state.active_page == "reports":
        import meeting_database as db
        import json
        
        # TOP BAR (Screenshot 4)
        col1, col2 = st.columns([3, 1])
        with col1:
            search_query = st.text_input("📁 Filter by report title or content...", placeholder="Search...")
        with col2:
            st.write("") # Spacer
            with st.popover("➕ Upload Recording", use_container_width=True):
                st.write("Process meetings recorded outside of RENA.")
                u_file = st.file_uploader("Choose a file", type=["mp3", "mp4", "wav"])
                if u_file:
                    temp_dir = Path("meeting_outputs/uploads")
                    temp_dir.mkdir(exist_ok=True)
                    temp_path = temp_dir / u_file.name
                    with open(temp_path, "wb") as f:
                        f.write(u_file.getbuffer())
                    
                    if st.button("🚀 Start AI Analysis", use_container_width=True):
                        with st.status("RENA is analyzing your recording...", expanded=True) as status:
                            st.write("👂 Transcribing audio...")
                            from meeting_notes_generator import AdaptiveMeetingNotesGenerator
                            generator = AdaptiveMeetingNotesGenerator()
                            
                            st.write("🧠 Extracting intelligence...")
                            generator.process(str(temp_path))
                            
                            status.update(label="✅ Analysis Complete!", state="complete", expanded=False)
                        st.success(f"Report for '{u_file.name}' is now available in your dashboard.")
                        time.sleep(1)
                        st.rerun()

        # FILTERS (Screenshot 4)
        f_col1, f_col2, f_col3 = st.columns(3)
        with f_col1: 
            time_filter = st.selectbox("📅 Anytime", ["Anytime", "Today", "Last 7 Days", "Last 30 Days"])
        with f_col2: 
            source_filter = st.selectbox("📥 Source", ["All Sources", "Google Meet", "Zoom", "Manual"])
        with f_col3: 
            folders = db.get_all_folders()
            folder_names = ["All Folders"] + [f['name'] for f in folders]
            selected_folder = st.selectbox("📂 Folder", folder_names)

        st.divider()
        
        # Fetch data
        meetings = db.search_meetings(search_query) if search_query else db.get_all_meetings()
        
        if not meetings:
            st.info("📭 No meeting reports found yet. Start by joining a meeting!")
        else:
            for meet in meetings:
                # Premium Card Layout (Replicating Screenshot 4)
                with st.container():
                    c1, c2, c3 = st.columns([0.1, 3, 1])
                    with c1:
                        st.markdown("📄")
                    with c2:
                        st.markdown(f"**{meet['title']}**")
                        st.caption(f"{meet['start_time']} • {meet['duration_minutes'] or '??'}m • {meet['organizer_name'] or 'Unknown'}")
                    with c3:
                        if st.button("View Details", key=f"view_{meet['id']}", use_container_width=True):
                            st.session_state.selected_meeting = meet['id']
                    
                    # If expanded/selected
                    if st.session_state.get('selected_meeting') == meet['id']:
                        import meeting_database as db
                        from payment_service import payments
                        
                        # Refresh meet data to get latest payment status
                        meet = db.get_meeting(meet['id']) or meet
                        
                        # Determine if summary is accessible
                        is_pro = profile.get('subscription_plan') in ['Pro', 'Enterprise']
                        is_unlocked = meet.get('is_summarized_paid') or is_pro
                        
                        st.markdown("---")
                        
                        # Always show Transcript (Free point)
                        with st.expander("📜 Full Transcript (Free Access)", expanded=not is_unlocked):
                            st.markdown(f"```\n{meet['transcript_text'] or 'No transcript available'}\n```")
                        
                        if is_unlocked:
                            with st.status("🧠 Deep Intelligence Report", expanded=True):
                                tab_sum, tab_chap, tab_intel, tab_sync = st.tabs([
                                    "📝 Summary", "🔖 Chapters", "📊 Intelligence", "🔗 Sync"
                                ])
                                
                                with tab_sum:
                                    st.markdown(meet.get('summary_text') or "*No summary available*")
                                    if meet.get('action_items'):
                                        st.markdown("### ✅ Action Items")
                                        try:
                                            items = json.loads(meet['action_items'])
                                            for item in items:
                                                if isinstance(item, dict):
                                                    st.markdown(f"- **{item.get('task')}** ({item.get('owner')}) - *Due: {item.get('deadline')}*")
                                                else: st.markdown(f"- {item}")
                                        except: st.write(meet['action_items'])
                                
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
                                    i_col1, i_col2 = st.columns(2)
                                    # ... (Sentiment & Engagement extraction)
                                    st.info("Additional AI insights (Sentiment, Engagement, Coaching) are displayed here.")
                                    
                                with tab_sync:
                                    st.write("Sync this report to your tools:")
                                    # ... (Sync buttons implementation)
                                    st.button("Mock Sync to CRM", disabled=True)
                        else:
                            # Paywall UI (Professional Look)
                            st.markdown(f"""
                                <div style="background: white; border-radius: 15px; padding: 40px; text-align: center; border: 1px dashed #cbd5e1; margin-top: 10px;">
                                    <div style="font-size: 3rem; margin-bottom: 20px;">🔒</div>
                                    <h3 style="margin-bottom: 10px;">Deep Intelligence is Locked</h3>
                                    <p style="color: #64748b; margin-bottom: 30px;">
                                        Transcription is free! Unlock the <b>AI Summary, Action Items, and Speaker Insights</b><br>
                                        to save time and focus on what matters.
                                    </p>
                                </div>
                            """, unsafe_allow_html=True)
                            
                            lock_col1, lock_col2 = st.columns(2)
                            with lock_col1:
                                if st.button(f"✨ Unlock Summary (1 Credit)", key=f"unlock_{meet['id']}", use_container_width=True, type="primary"):
                                    if profile.get('credits', 0) > 0:
                                        success, msg = db.unlock_meeting_summary(user_info['email'], meet['id'])
                                        if success:
                                            st.toast("✅ Summary Unlocked!")
                                            time.sleep(1)
                                            st.rerun()
                                        else: st.error(msg)
                                    else:
                                        st.warning("⚠️ You're out of credits! Upgrade to Pro for unlimited summaries.")
                            
                            with lock_col2:
                                if st.button("🚀 Upgrade to Pro (Unlimited)", key=f"up_lock_{meet['id']}", use_container_width=True):
                                    success, msg = payments.process_simulated_payment(user_info['email'], "pro_monthly")
                                    if success:
                                        st.success("✅ Welcome to PRO!")
                                        time.sleep(1)
                                        st.rerun()
                                    else: st.error(msg)
                    st.divider()

    # FEATURE: INTEGRATIONS (Screenshot 2)
    elif st.session_state.active_page == "integrations":
        from integrations_service import integrations
        import meeting_database as db
        st.subheader("Supercharge Your Workflow")
        
        # Load profile for credentials
        profile = db.get_user_profile(user_info['email']) or {}
        
        i_col1, i_col2, i_col3 = st.columns(3)
        
        with i_col1:
            st.markdown(f"""<div class="main-card">
                <b>📧 Gmail</b> <span style="font-size:0.75rem; color:#10b981;">● Connected</span><br>
                <small>AI-powered inbox insights</small>
            </div>""", unsafe_allow_html=True)
            if st.button("Fetch Inbox Highlights", use_container_width=True):
                with st.spinner("Analyzing emails..."):
                    try:
                        summaries = integrations.summarize_emails()
                        if isinstance(summaries, list):
                            if not summaries:
                                st.info("No recent emails found.")
                            for s in summaries: st.info(f"📩 {s}")
                        else: st.warning(summaries)
                    except Exception as e:
                        if "insufficientPermissions" in str(e):
                            st.error("🔑 Permission Error: RENA needs access to your Gmail. Please Logout and Sign in again to grant permission.")
                        elif "403" in str(e) or "accessNotConfigured" in str(e):
                            st.error("🚫 **Action Required:** The Gmail API is not enabled in your Google Project. Visit [Google Cloud Console](https://console.cloud.google.com/apis/library/gmail.googleapis.com) and click **'Enable'** to use this feature.")
                        else:
                            st.error(f"Error fetching emails: {e}")
            
        with i_col2:
            n_status = "● Connected" if profile.get('notion_token') else "○ Disconnected"
            n_color = "#10b981" if profile.get('notion_token') else "#94a3b8"
            st.markdown(f"""<div class="main-card">
                <b>📝 Notion</b> <span style="font-size:0.75rem; color:{n_color};">{n_status}</span><br>
                <small>Auto-sync reports to Notion</small>
            </div>""", unsafe_allow_html=True)
            with st.popover("Configure Notion", use_container_width=True):
                n_token = st.text_input("Notion API Token", value=profile.get('notion_token') or "", type="password")
                n_db = st.text_input("Database ID", value=profile.get('notion_db') or "")
                if st.button("Save Notion Connection", use_container_width=True):
                    db.update_user_profile(user_info['email'], {'notion_token': n_token, 'notion_db': n_db})
                    st.success("Configuration saved!")
                    time.sleep(1)
                    st.rerun()

        with i_col3:
            h_status = "● Connected" if profile.get('hubspot_api_key') else "○ Disconnected"
            h_color = "#10b981" if profile.get('hubspot_api_key') else "#94a3b8"
            st.markdown(f"""<div class="main-card">
                <b>🏢 CRM (HubSpot)</b> <span style="font-size:0.75rem; color:{h_color};">{h_status}</span><br>
                <small>Sync meetings to leads</small>
            </div>""", unsafe_allow_html=True)
            with st.popover("Configure CRM", use_container_width=True):
                crm_key = st.text_input("HubSpot API Key", value=profile.get('hubspot_api_key') or "", type="password")
                if st.button("Save HubSpot Key", use_container_width=True):
                    db.update_user_profile(user_info['email'], {'hubspot_api_key': crm_key})
                    st.success("Connection Saved!")
                    time.sleep(1)
                    st.rerun()

    # FEATURE: FOLDERS
    elif st.session_state.active_page == "folders":
        import meeting_database as db
        st.subheader("📁 Organize Your Meetings")
        
        col_f1, col_f2 = st.columns([1, 2])
        with col_f1:
            with st.form("new_folder"):
                st.write("**Create New Folder**")
                f_name = st.text_input("Folder Name")
                f_color = st.color_picker("Folder Color", "#6366f1")
                if st.form_submit_button("Create Folder"):
                    success, msg = db.create_folder(f_name, f_color)
                    if success: st.success(f"Created '{f_name}'")
                    else: st.error(msg)
        
        with col_f2:
            st.write("**Existing Folders**")
            all_folders = db.get_all_folders()
            for f in all_folders:
                st.markdown(f"""
                <div style="background: {f['color']}20; border-left: 5px solid {f['color']}; padding: 10px; margin-bottom: 5px; border-radius: 5px;">
                    <b>{f['name']}</b>
                </div>
                """, unsafe_allow_html=True)

    # FEATURE: FOR YOU
    elif st.session_state.active_page == "for_you":
        st.subheader("⭐ Personalized Highlights")
        st.info("Based on your recent meetings, here's what deserves your attention:")
        
        st.markdown("""
        <div class="main-card">
            <h4>💡 Insight: Project Deadlines</h4>
            <p>You mentioned 'Project Athena' in 3 meetings this week. Consider setting up a dedicated follow-up.</p>
        </div>
        <div class="main-card">
            <h4>📅 Action Required</h4>
            <p>You have 5 pending action items from 'Daily Sync'.</p>
        </div>
        """, unsafe_allow_html=True)

    # FEATURE: COACHING (Read.ai Replication)
    elif st.session_state.active_page == "coaching":
        import meeting_database as db
        st.markdown("<h2 style='color: #1e293b;'>🎯 Speaker Coaching</h2>", unsafe_allow_html=True)
        
        # Load real data or defaults
        insights = db.get_latest_coaching_insights()
        if not insights:
            # High-quality defaults if no data exists yet
            insights = {
                "clarity": {"talking_pace": "0 WPM", "filler_count": 0, "filler_words": []},
                "inclusion": {"non_inclusive_terms": 0, "tip": "Start a meeting to see inclusivity tips!"},
                "impact": {"bias": "N/A", "charisma_score": "Neutral", "charisma_detail": "No data yet."}
            }

        st.markdown("""
        <style>
            .coaching-card {
                background: white; border-radius: 12px; padding: 18px; 
                border: 1px solid #e2e8f0; margin-bottom: 15px; cursor: pointer;
                transition: transform 0.2s, box-shadow 0.2s;
                display: flex; justify-content: space-between; align-items: center;
            }
            .coaching-card:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.05); }
            .coaching-label { font-size: 0.95rem; font-weight: 600; color: #475569; display: flex; align-items: center; gap: 10px; }
            .coaching-val { font-size: 0.9rem; color: #64748b; }
            .section-header { font-size: 0.85rem; font-weight: 700; color: #94a3b8; text-transform: uppercase; margin: 25px 0 12px 0; }
            .detail-container { background: white; border-radius: 15px; padding: 30px; border: 1px solid #e2e8f0; min-height: 500px; }
            .stat-box { background: #f8fafc; border-radius: 10px; padding: 20px; text-align: center; border: 1px solid #f1f5f9; }
        </style>
        """, unsafe_allow_html=True)

        left_col, right_col = st.columns([1, 1.8], gap="large")

        with left_col:
            # 1. CLARITY
            st.markdown('<div class="section-header">Clarity</div>', unsafe_allow_html=True)
            if st.button(f"⏱️ Talking pace", key="c_pace", use_container_width=True): st.session_state.coach_topic = "pace"
            if st.button(f"💬 Filler words", key="c_filler", use_container_width=True): st.session_state.coach_topic = "filler"

            # 2. INCLUSION
            st.markdown('<div class="section-header">Inclusion</div>', unsafe_allow_html=True)
            if st.button(f"🤝 Non-inclusive terms ({insights['inclusion']['non_inclusive_terms']})", key="c_inc", use_container_width=True): st.session_state.coach_topic = "inclusion"

            # 3. IMPACT
            st.markdown('<div class="section-header">Impact</div>', unsafe_allow_html=True)
            if st.button(f"⚖️ Bias", key="c_bias", use_container_width=True): st.session_state.coach_topic = "bias"
            if st.button(f"✨ Charisma", key="c_charisma", use_container_width=True): st.session_state.coach_topic = "charisma"

        with right_col:
            topic = st.session_state.get('coach_topic', 'pace')
            st.markdown('<div class="detail-container">', unsafe_allow_html=True)
            
            if topic == "pace":
                st.subheader("⏱️ Talking pace")
                st.write("Your average rate of speech measured in words per minute (WPM). The target zone is 130-175 WPM.")
                st.markdown("<br>", unsafe_allow_html=True)
                d1, d2 = st.columns(2)
                d1.metric("Current Pace", insights['clarity']['talking_pace'])
                d2.metric("Target Zone", "130-175 WPM")
                st.info("💡 **Coach Tip:** Speaking at a moderate pace ensures your audience has time to process complex information and improves overall retention.")
            
            elif topic == "filler":
                st.subheader("💬 Filler words")
                st.write("Tracking common crutch words like 'um', 'uh', 'like', and 'basically'.")
                st.markdown("<br>", unsafe_allow_html=True)
                st.metric("Total Filler Count", f"{insights['clarity'].get('filler_count', 0)} per meeting")
                st.write(f"**Most Used:** {', '.join(insights['clarity'].get('filler_words', ['None detected']))}")
                st.success("✅ **Coach Tip:** Short pauses are more effective than filler words. Practice embracing silence while you think.")

            elif topic == "inclusion":
                st.subheader("🤝 Non-inclusive terms")
                st.write("Monitoring usage of gendered language or non-inclusive terminology.")
                st.markdown("<br>", unsafe_allow_html=True)
                st.metric("Total Flagged", insights['inclusion']['non_inclusive_terms'])
                st.info(f"💡 **Recommendation:** {insights['inclusion']['tip']}")

            elif topic == "bias":
                st.subheader("⚖️ Language Bias")
                st.write("Evaluating the transcript for potential conversational bias or leading language.")
                st.markdown("<br>", unsafe_allow_html=True)
                st.write(f"**Status:** {insights['impact']['bias']}")
                st.caption("AI analyzes whether questions are 'open' versus 'closed' and checks for inclusive phrasing.")

            elif topic == "charisma":
                st.subheader("✨ Charisma & Impact")
                st.write("Measuring your influence and positive resonance in the conversation.")
                st.markdown("<br>", unsafe_allow_html=True)
                st.metric("Charisma Score", insights['impact']['charisma_score'])
                st.write(f"**Detail:** {insights['impact']['charisma_detail']}")

            st.markdown('</div>', unsafe_allow_html=True)

    # FEATURE: WORKSPACE MANAGEMENT (Add People / Workflow Hub)
    elif st.session_state.active_page == "add_people":
        import meeting_database as db
        st.markdown("<h2 style='color: #1e293b;'>🏁 Workspace Management</h2>", unsafe_allow_html=True)
        
        tab_manage, tab_create = st.tabs(["👥 Manage Members", "🏗️ Create Workspace"])
        
        with tab_create:
            st.markdown("""
                <div style='background: #f0f9ff; padding: 15px; border-radius: 10px; border-left: 4px solid #0ea5e9; margin-bottom: 20px;'>
                    <h5 style='margin-bottom: 8px;'>🔒 Data Privacy & Security</h5>
                    <p style='font-size: 0.9rem; color: #475569;'>Workspaces allow teams to securely aggregate meeting metrics. By creating a workspace, you maintain ownership of your data while enabling RENA AI to provide deep group-level insights.</p>
                </div>
            """, unsafe_allow_html=True)
            
            with st.form("create_ws_form"):
                ws_name = st.text_input("Name your new organization", placeholder="Your workspace name, e.g., Acme Inc...")
                ws_desc = st.text_area("Description (Optional)")
                
                st.divider()
                st.markdown("### 📄 Legal & Compliance")
                st.write("To create an enterprise workspace, please review and accept the Data Processing Addendum (DPA).")
                
                with st.expander("🔍 View full Data Processing Addendum (DPA)"):
                    try:
                        with open("DATA_PROCESSING_AGREEMENT.md", "r") as f:
                            st.markdown(f.read())
                    except:
                        st.error("DPA file not found. Please contact support.")
                
                st.info("""
                **Quick Summary of Terms:**
                - **Privacy:** We only process data to provide your requested services.
                - **Security:** Industry-standard encryption and access controls are applied.
                - **Control:** You remain the Data Controller; RENA is your Data Processor.
                - **Deletion:** You can request data deletion at any time upon workspace termination.
                """)
                
                agree = st.checkbox("I have read and agree to the [Data Processing Addendum (DPA)](https://www.rena-ai.example.com/dpa) and [Terms of Service](https://www.rena-ai.example.com/tos)")
                if st.form_submit_button("Next Step"):
                    if not agree:
                        st.warning("Please agree to the Data Processing Agreement.")
                    elif not ws_name:
                        st.warning("Workspace name is required.")
                    else:
                        success, ws_id = db.create_workspace(ws_name, user_info['email'], ws_desc)
                        if success:
                            st.success(f"Workspace '{ws_name}' created successfully!")
                            st.rerun()
                        else:
                            st.error(f"Error: {ws_id}")

        with tab_manage:
            workspaces = db.get_user_workspaces(user_info['email'])
            if not workspaces:
                st.info("You don't belong to any workspaces yet. Create one to get started!")
            else:
                current_ws_id = st.session_state.get('active_workspace_id')
                if not current_ws_id:
                    st.info("Select a workspace from the sidebar to manage members.")
                else:
                    ws_info = next((w for w in workspaces if w['id'] == current_ws_id), None)
                    st.subheader(f"Managing: {ws_info['name']}")
                    
                    # Invite Form
                    with st.expander("➕ Invite New Member", expanded=False):
                        with st.form("invite_member"):
                            invite_email = st.text_input("Enter Gmail address")
                            invite_role = st.selectbox("Assign Role", ["member", "admin"])
                            if st.form_submit_button("Send Invitation"):
                                success, msg = db.add_workspace_member(current_ws_id, invite_email, invite_role)
                                if success: st.success(f"Invite sent to {invite_email}!")
                                else: st.error(msg)
                    
                    st.divider()
                    st.write("**Current Members**")
                    members = db.get_workspace_members(current_ws_id)
                    for m in members:
                        role_color = "#4338ca" if m['role'] == 'owner' else "#6366f1"
                        st.markdown(f"""
                        <div style='display: flex; justify-content: space-between; align-items: center; padding: 10px; border-bottom: 1px solid #eee;'>
                            <span>{m['user_email']}</span>
                            <span style='background: {role_color}20; color: {role_color}; padding: 2px 8px; border-radius: 12px; font-size: 0.8rem; font-weight: 600;'>{m['role'].upper()}</span>
                        </div>
                        """, unsafe_allow_html=True)

    # FEATURE: WORKSPACE CHAT
    elif st.session_state.active_page == "workspace_chat":
        import meeting_database as db
        ws_id = st.session_state.get('active_workspace_id')
        ws_name = st.session_state.get('active_workspace_name', 'General Chat')
        
        if not ws_id:
            st.warning("Please select or create a workspace first.")
        else:
            st.subheader(f"💬 {ws_name} Collaboration")
            
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
                                # Simple file saving logic
                                upload_dir = Path("meeting_outputs/uploads")
                                upload_dir.mkdir(exist_ok=True)
                                att_path = str(upload_dir / att.name)
                                with open(att_path, "wb") as f:
                                    f.write(att.getbuffer())
                                att_name = att.name
                                
                            db.send_workspace_message(ws_id, user_info['email'], user_info['name'], msg, att_path, att_name)
                            st.rerun()

    # FEATURE: SMART SCHEDULER
    elif st.session_state.active_page == "scheduler":
        from crm_service import scheduler
        st.subheader("🔗 Smart Scheduler")
        st.write("Share this link to let others book meetings with you automatically.")
        
        user_email = user_info['email']
        link = scheduler.generate_smart_link(user_email)
        
        st.code(link, language="text")
        if st.button("Copy Scheduling Link"):
            st.toast("Link copied to clipboard!")
            import pyperclip
            pyperclip.copy(link)

    elif st.session_state.active_page == "settings":
        import meeting_database as db
        st.markdown("<h2 style='color: #0f172a;'>⚙️ User Settings</h2>", unsafe_allow_html=True)
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
                st.markdown("**📍 Contact Locations**")
                h_addr = st.text_input("Home Address", value=profile.get('home_address') or "", placeholder="e.g., 123 Maple St, NY")
                o_addr = st.text_input("Office Address", value=profile.get('office_address') or "", placeholder="e.g., One Infinity Loop, Cupertino")
                
                st.markdown("<br>", unsafe_allow_html=True)
                if st.form_submit_button("✅ Save Changes", use_container_width=True):
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

    elif st.session_state.active_page == "manage":
        import meeting_database as db
        st.markdown("<h2 style='color: #0f172a;'>🛠️ App Management</h2>", unsafe_allow_html=True)
        st.write("Configure your dashboard themes, notifications, and bot behaviors.")
        
        profile = db.get_user_profile(user_info['email']) or {}
        
        with st.container():
            st.markdown('<div class="main-card">', unsafe_allow_html=True)
            with st.form("app_settings_form"):
                st.markdown("### 🎨 Dashboard & Display")
                c1, c2 = st.columns(2)
                with c1:
                    app_theme = st.radio("Theme Mode", ["Light", "Dark", "Custom"], 
                                         index=["Light", "Dark", "Custom"].index(profile.get('theme_mode', 'Light')))
                with c2:
                    notifs = st.toggle("System Notifications", value=bool(profile.get('notifications_enabled', 1)))
                    st.caption("Receive desktop alerts when meetings start.")
                
                st.divider()
                
                st.markdown("### 🎧 Audio & Hardware")
                audio_out = st.selectbox("Default Audio Output", ["Default System Speaker", "VB-CABLE Output", "Headphones (Bluetooth)"],
                                        index=["Default System Speaker", "VB-CABLE Output", "Headphones (Bluetooth)"].index(profile.get('audio_output_device', 'Default System Speaker')))
                st.info("💡 **Tip:** Use 'VB-CABLE Output' for the most reliable meeting recording quality.")
                
                st.divider()
                
                st.markdown("### 🤖 Bot Intelligence & Automation")
                col_b1, col_b2 = st.columns(2)
                with col_b1:
                    auto_join = st.toggle("Auto-Join Meetings", value=bool(profile.get('bot_auto_join', 1)))
                    st.caption("Allow RENA to enter scheduled meetings automatically.")
                with col_b2:
                    auto_rec = st.toggle("Enable Recording by Default", value=bool(profile.get('bot_recording_enabled', 1)))
                    st.caption("Start audio capture as soon as the bot enters.")
                
                st.divider()
                
                st.markdown("### ✨ AI Persona & Reporting")
                c_bot, c_lang = st.columns(2)
                with c_bot:
                    bot_name = st.text_input("Bot Persona Name", value=profile.get('bot_name', 'Rena AI | Meeting Assistant'))
                    st.caption("The name displayed when the bot joins a meeting.")
                with c_lang:
                    sum_lang = st.selectbox("Intelligence Output Language", ["English/Hindi", "English Only", "Hindi Only"],
                                           index=["English/Hindi", "English Only", "Hindi Only"].index(profile.get('summary_language', 'English/Hindi')))
                    st.caption("Default language for summaries and MOM reports.")

                st.markdown("<br>", unsafe_allow_html=True)
                if st.form_submit_button("💾 Save App Configuration", use_container_width=True):
                    updates = {
                        'theme_mode': app_theme,
                        'notifications_enabled': 1 if notifs else 0,
                        'audio_output_device': audio_out,
                        'bot_auto_join': 1 if auto_join else 0,
                        'bot_recording_enabled': 1 if auto_rec else 0,
                        'bot_name': bot_name,
                        'summary_language': sum_lang
                    }
                    if db.update_user_profile(user_info['email'], updates):
                        st.success("Platform settings saved! Changes will take effect immediately.")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("Failed to save configuration.")
            st.markdown('</div>', unsafe_allow_html=True)

    elif st.session_state.active_page == "add_live":
        st.subheader("Join a Live Meeting")
        st.info("💡 **How it works:** Enter any Google Meet URL, and RENA will join as a guest to record and transcribe the session for you.")
        live_url = st.text_input("Enter the Meeting URL (Google Meet, Zoom, etc.)", placeholder="https://meet.google.com/abc-defg-hij")
        
        if st.button("🔴 Join & Record Now", use_container_width=True):
            if not live_url:
                st.warning("Please provide a meeting URL.")
            else:
                import meeting_database as db
                success, msg = db.inject_bot_now(live_url)
                if success:
                    st.success("🚀 RENA is on the way! The bot will join and start recording in a few seconds.")
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
                        <span style="font-size: 1.5rem;">🤖</span>
                        <h3 style="margin: 0; color: #0f172a;">RENA Intelligence Hub</h3>
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
                import rena_bot_pilot
                import meeting_database as db
                events = rena_bot_pilot.get_upcoming_events(max_results=10)
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
                                        st.markdown("<div class='bot-status-active' style='font-size: 0.7rem;'>🛡️ RENA: JOINING...</div>", unsafe_allow_html=True)
                                    elif bot_stat == "CONNECTED":
                                        st.markdown("<div style='color: #10b981; font-size: 0.7rem; font-weight: 800;'>🛡️ RENA: CONNECTED</div>", unsafe_allow_html=True)
                                    else:
                                        st.markdown("<span style='color: #10b981; font-size: 0.7rem; font-weight: 800;'>Status: AUTO-JOIN: ON</span>", unsafe_allow_html=True)
                                    
                                    if st.button("Cancel Auto Join", key=f"can_{meet_id}", use_container_width=True):
                                        db.toggle_meeting_skip(meet_id, True, title=event.get('summary'), start_time=start_time)
                                        st.rerun()
                            st.divider()
            with col_stat:
                st.subheader("Quick Access")
                
                # --- INSTANT JOIN ---
                with st.expander("⚡ Instant Join", expanded=True):
                    inst_url = st.text_input("Meeting Link", placeholder="meet.google.com/...", label_visibility="collapsed")
                    if st.button("🚀 Join Now", use_container_width=True, type="primary"):
                        if inst_url:
                            # Silent background launch
                            CREATE_NO_WINDOW = 0x08000000
                            subprocess.Popen(f'title RENA_INSTANT_JOIN && {sys.executable} rena_bot_pilot.py --url "{inst_url}"', 
                                             shell=True,
                                             creationflags=CREATE_NO_WINDOW if os.name == 'nt' else 0)
                            st.toast(f"✅ RENA is joining {inst_url}...")
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
                    
                    if st.button("🚀 Confirm & Create", use_container_width=True):
                        if not m_title:
                            st.warning("Please enter a meeting title.")
                        else:
                            import rena_bot_pilot
                            start_dt = datetime.combine(m_date, m_time)
                            start_iso = start_dt.isoformat() + "Z"
                            
                            with st.spinner("Syncing with Google Calendar..."):
                                meet_link, status = rena_bot_pilot.create_google_meeting(m_title, start_iso, m_duration)
                                
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
                                        st.success(f"🚀 Meeting Created & RENA is joining: {m_title}")
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
                            if st.button("🔴 Join & Record Now", key="join_now_btn", use_container_width=True):
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
            
            s_link = f"https://rena.ai/schedule/{user_info['email']}/active"
            st.code(s_link, language="text")
            if st.button("📋 Copy My link", use_container_width=True):
                import pyperclip
                pyperclip.copy(s_link)
                st.success("Link copied to clipboard!")
            
            st.divider()
            st.info("💡 **Tip:** Embed this link in your email signature to automate your meeting bookings.")

# --- 6. FOOTER ---
st.markdown("---")
st.caption("RENA AI v2.2 | Full Automation Enbaled | Feature Parity: ACTIVE")
