import os
import sys
import time
import subprocess
import signal
import re
import base64
import threading
from pathlib import Path
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

import pyperclip
import json

# --- GOOGLE CALENDAR INTEGRATIONS ---
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

import meeting_database as db

# --- HELPERS ---
def is_meet_url(text: str) -> bool:
    if not isinstance(text, str): return False
    return "meet.google.com/" in text

def is_zoom_url(text: str) -> bool:
    if not isinstance(text, str): return False
    return "zoom.us/j/" in text or "zoom.us/my/" in text or "zoom.us/s/" in text or ".zoom.us/j/" in text

def normalize_url(url: str) -> str:
    """Ensure a URL has a proper https:// scheme.
    Handles cases where users paste 'meet.google.com/xxx' without the protocol.
    Playwright's page.goto() requires an absolute URL or it crashes.
    """
    if not url:
        return url
    url = url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    return url

# --- GOOGLE SIGN-IN (DEPRECATED FOR WEB FLOW) ---
def run_gmail_registration():
    """Sign-in handled via Web OAuth flow in main.py"""
    return "success"

# --- CALENDAR OPERATIONS ---
def get_service(user_email=None):
    """Build and return the Calendar service with refreshed credentials from DB."""
    SCOPES = [
        'openid',
        'https://www.googleapis.com/auth/userinfo.profile',
        'https://www.googleapis.com/auth/userinfo.email',
        'https://www.googleapis.com/auth/calendar',
        'https://www.googleapis.com/auth/gmail.readonly',
        'https://www.googleapis.com/auth/gmail.send',
        'https://www.googleapis.com/auth/drive.metadata.readonly'
    ]
    
    if not user_email:
        user_email = "default@rena.ai"

    serialized_token = db.get_user_token(user_email)
    if not serialized_token: 
        print(f"No token found for {user_email}")
        return None

    try:
        creds_data = json.loads(serialized_token)
        creds = Credentials.from_authorized_user_info(creds_data, SCOPES)

        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request as GoogleRequest
            creds.refresh(GoogleRequest())
            db.exec_commit("UPDATE users SET google_token = ?, updated_at = CURRENT_TIMESTAMP WHERE email = ?", 
                         (creds.to_json(), user_email))

        return build('calendar', 'v3', credentials=creds)
    except Exception as e:
        print(f"Auth/API Error for {user_email}: {e}")
        return None

def get_upcoming_events(user_email=None, max_results=5):
    """Fetches meetings using a clean API call."""
    service = get_service(user_email)
    if not service: return []
    try:
        # Look back 180 minutes (3 hours) to catch ongoing meetings
        time_now = datetime.now(timezone.utc) - timedelta(minutes=180)
        now_iso = time_now.isoformat().replace('+00:00', 'Z')
        
        events_result = service.events().list(
            calendarId='primary', 
            timeMin=now_iso, 
            maxResults=max_results, 
            singleEvents=True, 
            orderBy='startTime'
        ).execute()
        
        return events_result.get('items', [])
    except Exception as e:
        print(f"Calendar Error: {e}")
        return []

def create_google_meeting(summary, start_time_iso, duration_minutes=30):
    """
    Creates a Google Calendar event with a Google Meet link.
    Replicates the 'Schedule Meeting' feature.
    """
    service = get_service()
    if not service: return None, "Authentication required."
    
    try:
        # Calculate end time
        start_dt = datetime.fromisoformat(start_time_iso.replace('Z', '+00:00'))
        end_dt = start_dt + timedelta(minutes=duration_minutes)
        end_time_iso = end_dt.isoformat().replace('+00:00', 'Z')
        
        event = {
            'summary': summary,
            'description': 'Meeting created via Renata AI Assistant',
            'start': {'dateTime': start_time_iso, 'timeZone': 'UTC'},
            'end': {'dateTime': end_time_iso, 'timeZone': 'UTC'},
            'conferenceData': {
                'createRequest': {
                    'requestId': f"rena_{int(time.time())}",
                    'conferenceSolutionKey': {'type': 'hangoutsMeet'}
                }
            }
        }
        
        event = service.events().insert(
            calendarId='primary', 
            body=event, 
            conferenceDataVersion=1
        ).execute()
        
        meet_link = event.get('hangoutLink')
        return meet_link, "Success"
    except Exception as e:
        return None, str(e)

def get_user_info():
    """Extract user information from Google token to resolve DB preferences."""
    if not os.path.exists('token.json'): return None
    try:
        from google.oauth2.credentials import Credentials
        creds = Credentials.from_authorized_user_file('token.json')
        service = build('oauth2', 'v2', credentials=creds)
        google_info = service.userinfo().get().execute()
        return google_info
    except Exception as e:
        print(f"User Discovery Error: {e}")
        return None

# --- BOT CONFIGURATION ---
PERMANENT_BOT_EMAIL = "chandisha.das.fit.cse22@teamfuture.in"
PERMANENT_BOT_PASS = "123Chandisha#"
BOT_SESSION_DIR = os.path.join(os.getcwd(), "bot_session")

# ─────────────────────────────────────────────────────────────────────────────
# CONCURRENT MEETING SLOT POOL
# Each slot is an independent Playwright browser profile directory.
# Slot 0  → bot_session/          (original, already logged-in session)
# Slot 1+ → bot_session/slot_<n>/ (auto-created; requires one-time bot login)
# Set MAX_CONCURRENT_MEETINGS to however many meetings can run at once.
# NOTE: Each extra slot needs its own VB-Cable / audio device if you want
#       separate audio streams. A simple workaround is to record system
#       audio output (all meetings mix into one stream on the same machine).
# ─────────────────────────────────────────────────────────────────────────────
MAX_CONCURRENT_MEETINGS = 3

_slot_lock   = threading.Lock()
_free_slots  = list(range(MAX_CONCURRENT_MEETINGS))   # [0, 1, 2]
_active_jobs = {}   # meeting_id -> threading.Thread

def _acquire_slot():
    """Grab a free browser slot. Returns slot index or None if all busy."""
    with _slot_lock:
        if _free_slots:
            return _free_slots.pop(0)
    return None

def _release_slot(slot: int):
    """Return a slot back to the pool after a meeting ends."""
    with _slot_lock:
        if slot not in _free_slots:
            _free_slots.append(slot)
            _free_slots.sort()

def _get_session_dir(slot: int) -> str:
    """Slot 0 uses the original bot_session folder; extra slots get sub-dirs."""
    if slot == 0:
        return BOT_SESSION_DIR
    path = os.path.join(BOT_SESSION_DIR, f"slot_{slot}")
    os.makedirs(path, exist_ok=True)
    return path

def _run_meeting_in_thread(meet_url: str, meeting_id: str, user_email: str,
                           rec_enabled: bool, slot: int):
    """
    Worker function executed in a daemon thread.
    Joins ONE meeting using its own browser slot, then releases the slot.
    """
    session_dir = _get_session_dir(slot)
    print(f"[Slot {slot}] Starting join for {meeting_id} → {meet_url} (user: {user_email})")
    thread_bot = RenaMeetingBot(user_email=user_email, session_dir=session_dir)
    try:
        if is_meet_url(meet_url):
            thread_bot.join_google_meet(meet_url, record=rec_enabled, db=db,
                                        meeting_id=meeting_id, user_email=user_email)
        elif is_zoom_url(meet_url):
            thread_bot.join_zoom_meeting(meet_url, record=rec_enabled, db=db,
                                         meeting_id=meeting_id, user_email=user_email)
        else:
            print(f"[Slot {slot}] Unknown URL type: {meet_url}")
            db.update_bot_status(meeting_id, "FAILED", note="Unknown meeting URL type")
    except Exception as e:
        print(f"[Slot {slot}] Thread error for {meeting_id}: {e}")
        db.update_bot_status(meeting_id, "FAILED", note=f"Thread error: {e}")
    finally:
        _release_slot(slot)
        _active_jobs.pop(meeting_id, None)
        print(f"[Slot {slot}] Released. Free slots: {sorted(_free_slots)}")

class RenaMeetingBot:
    def __init__(self, bot_name="Renata AI | Meeting Assistant",
                 audio_device="audio=CABLE Output (VB-Audio Virtual Cable)",
                 user_email=None, session_dir=None):
        self.user_email = user_email
        if user_email:
            try:
                profile = db.get_user_profile(user_email)
                if profile and profile.get('bot_name'):
                    bot_name = profile['bot_name']
            except: pass

        self.bot_name     = bot_name
        self.audio_device = audio_device
        self.output_dir   = Path("meeting_outputs") / "recordings"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.audio_process  = None
        self.recording_path = None
        # Allow override so concurrent slots use different browser profiles
        self.session_dir = session_dir if session_dir else BOT_SESSION_DIR

    def bot_setup_login(self):
        """Hidden feature to allow manual login for the bot's permanent email."""
        print(f"Opening Browser for Bot Login...")
        print(f"Please log in to {PERMANENT_BOT_EMAIL}")
        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(
                self.session_dir,
                headless=False,
                args=["--start-maximized"]
            )
            page = browser.pages[0]
            page.goto("https://accounts.google.com/")
            print("Waiting for you to finish login. Close the browser when done.")
            while len(browser.pages) > 0:
                time.sleep(1)
        print("Bot Login Session Saved.")

    def automate_google_login(self, page):
        """Automated login for the bot's Gmail account with handling for multiple scenarios."""
        print(f"DEBUG: Attempting automated login for {PERMANENT_BOT_EMAIL}...")
        try:
            # Scenario 1: Choose an account screen
            if "AccountChooser" in page.url or page.locator('div[data-email="' + PERMANENT_BOT_EMAIL + '"]').count() > 0:
                print("DEBUG: Account chooser detected. Selecting bot account...")
                page.click('div[data-email="' + PERMANENT_BOT_EMAIL + '"]')
                time.sleep(2)

            # Scenario 2: Email input screen
            if page.locator('input[type="email"]').is_visible(timeout=5000):
                page.fill('input[type="email"]', PERMANENT_BOT_EMAIL)
                page.click('#identifierNext')
                print("DEBUG: Entered email.")
                page.wait_for_load_state("networkidle")
                time.sleep(2)
            
            # Scenario 3: Password input screen
            # Wait for password field to be interactive
            password_field = page.locator('input[type="password"]')
            password_field.wait_for(state="visible", timeout=10000)
            password_field.fill(PERMANENT_BOT_PASS)
            
            # Click next and wait for navigation
            page.click('#passwordNext')
            print("DEBUG: Entered password. Waiting for redirection...")
            
            # Check for "Security check" or "Recovery email" - though automated bypass is hard, we wait a bit
            page.wait_for_load_state("networkidle")
            time.sleep(5)
            
            # Handle "Keep me signed in" or "Update recovery" if they appear
            try:
                if "Confirm your recovery email" in page.content():
                    print("DEBUG: Security prompt detected. Trying to skip...")
                    page.click('div[role="button"]:has-text("Confirm")', timeout=2000)
            except: pass

            return "accounts.google.com" not in page.url
        except Exception as e:
            print(f"DEBUG: Automated login failed attempt: {e}")
            return False

    def start_audio_recording(self, filename):
        self.recording_path = self.output_dir / f"{filename}.wav"
        # Dynamic device selection
        cmd = ["ffmpeg", "-y", "-f", "dshow", "-i", self.audio_device, str(self.recording_path)]
        self.audio_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)

    def stop_audio_recording(self):
        if self.audio_process:
            self.audio_process.send_signal(signal.CTRL_BREAK_EVENT)
            self.audio_process.wait()

    def join_zoom_meeting(self, zoom_url, record=True, db=None, meeting_id=None, user_email=None):
        """Joins a Zoom meeting via the web client."""
        if not meeting_id:
            # Generate a temporary ID for URL-based joins
            meeting_id = f"zoom_live_{int(time.time())}"
        
        zoom_url = normalize_url(zoom_url)  # Ensure https:// prefix
        print(f"DEBUG: join_zoom_meeting called for {zoom_url} (User: {user_email})")
        
        # Transform URL to force web client: /j/123 -> /wc/join/123
        wc_url = zoom_url.replace("/j/", "/wc/join/").replace("/s/", "/wc/join/")
        
        try:
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    self.session_dir,
                    headless=False,
                    args=[
                        "--use-fake-ui-for-media-stream",
                        "--use-fake-device-for-media-stream",
                        "--autoplay-policy=no-user-gesture-required",
                        "--start-maximized"
                    ]
                )
                page = context.pages[0]
                Stealth().apply_stealth_sync(page)
                
                print(f"Navigating to Zoom Web Client: {wc_url}")
                if db and meeting_id: db.update_bot_status(meeting_id, "FETCHING", "Navigating to Zoom Meeting...")
                page.goto(wc_url)
                
                # Wait for name input
                try:
                    page.wait_for_selector('input[name="input-name"]', timeout=10000)
                    page.fill('input[name="input-name"]', self.bot_name)
                    print(f"Entered bot name: {self.bot_name}")
                    page.click('button:has-text("Join")')
                except:
                    print("Name input not found, maybe already joined or cached.")

                # Handle Zoom specifics (Mute/Uncam)
                if db and meeting_id: db.update_bot_status(meeting_id, "CONNECTING", "Entering credentials...")
                time.sleep(10) # Wait for join to complete
                
                # Look for "Join Audio by Computer" if it pops up
                try:
                    audio_btn = page.locator('button:has-text("Join Audio by Computer")')
                    if audio_btn.count() > 0:
                        audio_btn.click()
                        print("Joined audio by computer")
                except: pass

                # Mute & Stop Video
                try:
                    print("Muted and Camera OFF (Zoom Shortcuts)")
                except: pass

                if db and meeting_id: db.update_bot_status(meeting_id, "LIVE", "Renata is now in the Zoom call.")

                if record:
                    # Start recording the local audio output
                    self.start_audio_recording(f"Zoom_Meeting_{int(time.time())}")
                    print(f"RECORDING STARTED: {self.recording_path}")

                # Keep session alive
                print("Zoom Session LIVE. Monitoring for exit...")
                if db and meeting_id:
                    db.set_meeting_bot_status(meeting_id, "CONNECTED", user_email=user_email)
                    db.update_meeting_bot_note(meeting_id, "Zoom Recording Active")

                while True:
                    # Check if page is closed or meeting ended
                    try:
                        if page.is_closed() or page.locator('button:has-text("Leave")').count() == 0:
                             # Logic for leaving if alone can be added here
                             pass
                    except: break
                    time.sleep(10)

                if record: self.stop_audio_recording()
                if db and meeting_id: db.set_meeting_bot_status(meeting_id, "COMPLETED")
                
        except Exception as e:
            print(f"Zoom Error: {e}")

    def join_google_meet(self, meet_url, record=True, db=None, meeting_id=None, user_email=None):
        if not meeting_id:
            meeting_id = f"meet_live_{int(time.time())}"
            
        meet_url = normalize_url(meet_url)  # Ensure https:// prefix
        print(f"DEBUG: join_google_meet called for {meet_url} (User: {user_email})")
        try:
            with sync_playwright() as p:
                # ... (existing setup) ...
                print("DEBUG: Launching Browser Context (Visible mode for reliability)...")
                context = p.chromium.launch_persistent_context(
                    self.session_dir,
                    headless=False,
                    args=[
                        "--use-fake-ui-for-media-stream",
                        "--use-fake-device-for-media-stream",
                        "--autoplay-policy=no-user-gesture-required",
                        "--disable-blink-features=AutomationControlled",
                        "--start-maximized",
                        "--disable-notifications",
                        "--no-sandbox",
                        "--disable-setuid-sandbox"
                    ]
                )
                page = context.pages[0]
                Stealth().apply_stealth_sync(page)
                
                print(f"DEBUG: Navigating to {meet_url}")
                page.goto(meet_url)
                time.sleep(5)

                # ... (login check, mute, join click logic same as before) ...
                # --- READ.AI STYLE AUTO-JOIN MECHANISM ---
                # Check if we can join as a Guest (No account needed)
                try:
                    name_input = page.locator('input[placeholder*="What\'s your name"], input[aria-label*="What\'s your name"]').first
                    if name_input.count() > 0:
                        bot_display_name = self.bot_name
                        print(f"DEBUG: Guest mode detected. Joining as '{bot_display_name}'...")
                        name_input.fill(bot_display_name)
                        time.sleep(1)
                        # Try Enter first, then look for any button that says Join
                        page.keyboard.press("Enter")
                        time.sleep(2)
                        
                        # Aggressive click on any Join button that appeared after Enter or before
                        page.evaluate('''() => {
                            const btns = Array.from(document.querySelectorAll('button, div[role="button"], span'));
                            const b = btns.find(x => x.innerText.includes('Join') || x.innerText.includes('Ask'));
                            if (b) b.click();
                        }''')
                        time.sleep(2)
                except: pass

                # Fallback: If still on login page, use the system-managed bot account
                if "accounts.google.com" in page.url:
                    print(f"DEBUG: Guest join not available. Using system bot account {PERMANENT_BOT_EMAIL}...")
                    if db and meeting_id: db.update_bot_status(meeting_id, "CONNECTING", "Logging in with bot account...")
                    login_success = self.automate_google_login(page)
                    if login_success:
                        print("DEBUG: Login handled. Returning to Meet...")
                        page.goto(meet_url) 
                        time.sleep(5)
                    else:
                        print("DEBUG: Login failed. Meeting may be restricted.")

                # Dismiss any camera/microphone error dialogs
                print("Dismissing any permission dialogs...")
                try:
                    # Close "Camera not found" or similar error dialogs
                    close_btns = page.locator('button[aria-label="Dismiss"], button:has-text("Got it"), button:has-text("Dismiss")').all()
                    for btn in close_btns:
                        try:
                            btn.click(timeout=1000)
                            print("Dismissed error dialog")
                        except: pass
                except: pass

                # Mute Mic & Camera (Multiple Methods for Reliability)
                print("Ensuring mic and camera are OFF...")
                time.sleep(3)  # Wait for page to fully load
                try:
                    # Method 1: Keyboard shortcuts (toggle twice to ensure OFF state)
                    # First, check current state and toggle if needed
                    page.keyboard.press("Control+d")  # Mic
                    time.sleep(0.5)
                    page.keyboard.press("Control+e")  # Camera
                    time.sleep(1)
                    
                    # Method 2: Click buttons to ensure they're OFF
                    try:
                        # Look for "Turn off microphone" button (means it's ON, so click to turn OFF)
                        mic_on_btn = page.locator('button[aria-label*="Turn off microphone" i]').first
                        if mic_on_btn.count() > 0:
                            mic_on_btn.click()
                            print("Turned OFF microphone")
                    except: pass
                    
                    try:
                        # Look for "Turn off camera" button (means it's ON, so click to turn OFF)
                        cam_on_btn = page.locator('button[aria-label*="Turn off camera" i]').first
                        if cam_on_btn.count() > 0:
                            cam_on_btn.click()
                            print("Turned OFF camera")
                    except: pass
                    
                    print("Mic and camera are OFF")
                except Exception as e:
                    print(f"Mute operation: {e}")

                # Auto-click "Ask to join" or "Join now" button
                print("Looking for Join button...")
                time.sleep(5) # Wait for page stabilty
                try:
                    # Very aggressive join button detection
                    join_selectors = [
                        '//span[contains(text(), "Join now")]',
                        '//span[contains(text(), "Ask to join")]',
                        '//span[contains(text(), "Join meeting")]',
                        'button:has-text("Join now")',
                        'button:has-text("Ask to join")',
                        'button:has-text("Join meeting")',
                        '[aria-label="Join now"]',
                        '[aria-label="Ask to join"]',
                        '[aria-label="Join meeting"]',
                        'div[role="button"]:has-text("Join now")',
                        'div[role="button"]:has-text("Ask to join")',
                        'div[role="button"]:has-text("Join meeting")',
                        '//div[contains(text(), "Join now")]',
                        '//div[contains(text(), "Ask to join")]'
                    ]
                    
                    if db and meeting_id: db.update_bot_status(meeting_id, "CONNECTING", "Ready to join...")
                    
                    clicked = False
                    # Loop a few times as the button might appear after a delay
                    for attempt in range(5):
                        for selector in join_selectors:
                            try:
                                btn = page.locator(selector).first
                                if btn.count() > 0 and btn.is_visible(timeout=2000):
                                    print(f"DEBUG: Found button with selector: {selector}")
                                    btn.click(force=True)
                                    print(f"SUCCESS: Clicked join button: {selector}")
                                    clicked = True
                                    break
                            except: continue
                        if clicked: break
                        print(f"DEBUG: Join button not found yet (attempt {attempt+1}/5)...")
                        time.sleep(2)
                    
                    if not clicked:
                        print("Join button not found with standard selectors, trying forced script click...")
                        # Fallback: Find any button that looks like a join button and click it
                        page.evaluate('''() => {
                            const buttons = Array.from(document.querySelectorAll('button, div[role="button"], span'));
                            const joinBtn = buttons.find(b => 
                                b.innerText.includes('Join now') || 
                                b.innerText.includes('Ask to join')
                            );
                            if (joinBtn) joinBtn.click();
                        }''')
                        
                except Exception as e: 
                    print(f"Join click system failed: {e}")

                # Wait for Admission
                print("Waiting in lobby (infinite loop until admitted)...")
                try:
                    # Look for clues that we are in the meeting
                    # 1. "You're waiting to be admitted" text
                    # 2. Meeting control bar appearing
                    # 3. List of participants
                    while True:
                        if page.locator('button[aria-label*="Leave call" i], button[aria-label*="Leave meeting" i]').count() > 0:
                            print("Admitted to Google Meet!")
                            if db and meeting_id: 
                                db.update_bot_status(meeting_id, "CONNECTED", note="Recording active")
                            break
                        
                        # Check for "Someone will let you in soon"
                        if page.locator('span:has-text("Someone will let you in soon"), div:has-text("You\'re waiting to be admitted")').count() > 0:
                            if db and meeting_id: db.update_bot_status(meeting_id, "IN_LOBBY", note="In Lobby - Waiting for host")
                        
                        time.sleep(5)
                except Exception as e:
                    print(f"Lobby wait error: {e}")

                if record:
                    # Start recording the local audio output
                    self.start_audio_recording(f"Meet_Meeting_{int(time.time())}")
                    print(f"RECORDING STARTED: {self.recording_path}")
                
                # Smart Meeting Monitor - Auto-leave when meeting ends
                print("Monitoring meeting status...")
                start_monitor = time.time()
                alone_since = None  # Track when bot became alone
                
                while True:
                    time.sleep(5)
                    try:
                        # Check 1: Browser closed
                        if page.is_closed(): 
                            print("Browser closed.")
                            break
                        
                        # Check 2: "You left" screen
                        if page.locator('text="You left the meeting"').count() > 0 or \
                           page.locator('text="Return to home screen"').count() > 0:
                            print("Meeting ended (detected exit screen).")
                            break
                        
                        # Check 3: URL changed to home
                        if "meet.google.com" in page.url and len(page.url.split('/')) <= 3:
                            print("Meeting ended (returned to home).")
                            break
                        
                        # Check 4: Participant count - auto-leave if alone for 5 mins
                        try:
                            # Try to count participants in the meeting
                            participant_elements = page.locator('[data-participant-id]').count()
                            
                            if participant_elements <= 1:  # Only bot remains
                                if alone_since is None:
                                    alone_since = time.time()
                                    print("Bot is alone in meeting. Will auto-leave in 1 min if no one joins...")
                                else:
                                    alone_duration = (time.time() - alone_since) / 60
                                    if alone_duration >= 1: # Reduced to 1 minute as requested for automation
                                        print("Auto-leaving: Bot alone for 1+ minute.")
                                        # Click leave button
                                        try:
                                            page.click('button[aria-label="Leave call"]', timeout=3000)
                                        except: pass
                                        break
                            else:
                                # Reset alone timer if others join
                                if alone_since is not None:
                                    print("Others joined, continuing meeting...")
                                alone_since = None
                        except:
                            pass  # Participant count check failed, continue monitoring
                            
                    except Exception as e:
                        print(f"Monitor error: {e}")
                        break

            # MEETING ENDED - CLEANUP & PIPELINE
            print("Meeting Finished. Stopping recording...")
            self.stop_audio_recording()
            
            # TRIGGER PIPELINE with detailed logging
            if db and meeting_id and self.recording_path and os.path.exists(self.recording_path):
                print("=" * 60)
                print("POST-MEETING PIPELINE ACTIVATED")
                print("=" * 60)
                db.update_bot_status(meeting_id, "PROCESSING", note="Meeting ended - Generating PDF...")
                
                try:
                    # Import and run the generator directly for better logging
                    print(f"Audio File: {self.recording_path}")
                    print("Stage 1/2: Running Gemini 3.0 Flash Priority (Transcription + Diarization)...")
                    
                    import meeting_notes_generator
                    generator = meeting_notes_generator.AdaptiveMeetingNotesGenerator(
                        audio_path=str(self.recording_path)
                    )
                    
                    # This calls Diarization (Local), Gemini Transcription, Gemini Summary, and Export
                    generator.process_meeting(str(self.recording_path))
                    
                    # NEW: Save all intelligence back to the database for Analytics/Dashboard
                    # Special: Read PDF and convert to base64 for Cloud Sync (Vercel)
                    p_blob = None
                    if generator.last_pdf_path and os.path.exists(generator.last_pdf_path):
                        try:
                            with open(generator.last_pdf_path, "rb") as f:
                                p_blob = base64.b64encode(f.read()).decode('utf-8')
                            print("PDF Encoded for Cloud sync (Dashboard Support).")
                        except Exception as e:
                            print(f"PDF Encoding for cloud failed: {e}")

                    print("Saving results to database...")
                    db.save_meeting_results(
                        meeting_id=meeting_id,
                        transcript=json.dumps(generator.structured_transcript),
                        summary=generator.intel.get('summary_en', ''),
                        action_items=generator.intel.get('actions', []),
                        speaker_stats=generator.intel.get('speaker_analytics', {}),
                        engagement=generator.intel.get('engagement_metrics', {}),
                        pdf_path=generator.last_pdf_path,
                        json_path=generator.last_json_path,
                        pdf_blob=p_blob
                    )
                    
                    print("=" * 60)
                    print("GEMINI 3.0 PIPELINE COMPLETE!")
                    print("=" * 60)
                    
                    # Update database with results
                    db.update_bot_status(meeting_id, "COMPLETED", note="Report ready")
                    
                except Exception as e:
                    print(f"Pipeline Failed: {e}")
                    import traceback
                    traceback.print_exc()
                    db.update_bot_status(meeting_id, "FAILED", note="Processing failed - Check logs")
        except Exception as e:
            print(f"FATAL ERROR in join_google_meet: {e}")
            import traceback
            traceback.print_exc()
            if db and meeting_id:
                db.update_bot_status(meeting_id, "FAILED", note=f"Join failed: {str(e)}")

    def record_manual_audio(self):
        # Create folder with unique ID
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        manual_recording_dir = self.output_dir / f"manual_{timestamp}"
        manual_recording_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"Manual Recording Started. Saving to {manual_recording_dir}")
        print("Capturing system audio... Press Ctrl+C to stop.")
        
        try:
            filename_base = f"manual_recording_{timestamp}"
            self.start_audio_recording(filename_base)
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping manual recording...")
        finally:
            self.stop_audio_recording()
            print(f"Manual recording saved to {self.recording_path}")

def run_auto_pilot(user_email):
    """
    Main background loop for Renata — MULTI-MEETING, MULTI-ACCOUNT.

    Every 30 s this loop:
      1. Scans Gmail for the operator account.
      2. Picks up ALL 'JOIN_PENDING' rows from ANY user and dispatches each
         into its own daemon thread + browser slot (up to MAX_CONCURRENT_MEETINGS).
      3. Scans Google Calendar for EVERY connected account in the DB and
         auto-joins upcoming meetings for each — also in parallel threads.
    """
    import meeting_database as db
    from gmail_scanner_service import gmail_scanner
    from dateutil import parser

    print(f"╔{'='*58}╗")
    print(f"║  Renata Auto-Pilot  │  operator: {user_email}")
    print(f"║  Max simultaneous meetings : {MAX_CONCURRENT_MEETINGS}")
    print(f"╚{'='*58}╝")

    session_handled_ids: set = set()   # IDs already dispatched this session

    while True:
        try:
            # -- Operator profile (needed for Gmail scan) --
            profile = db.get_user_profile(user_email)
            if not profile:
                print("Operator profile not found. Retrying in 60s...")
                time.sleep(60)
                continue

            # 1. GMAIL SCAN (operator account only)
            try:
                print("Scanning Gmail...")
                gmail_scanner.scan_inbox(user_email)
            except Exception as e:
                print(f"Gmail scan error: {e}")

            # 2. LIVE JOIN — every pending request, every user, all in parallel
            print("Checking for live join intents (all users)...")
            pending_joins = db.fetch_all(
                "SELECT * FROM meetings WHERE bot_status = 'JOIN_PENDING' ORDER BY created_at ASC"
            )

            for pending in pending_joins:
                m_id            = pending['meeting_id']
                meet_url        = pending.get('meet_url', '')
                requester_email = pending.get('user_email', user_email)

                if m_id in session_handled_ids:
                    db.update_bot_status(m_id, "COMPLETED", note="Already handled")
                    continue

                if not meet_url:
                    db.update_bot_status(m_id, "FAILED", note="No meeting URL")
                    continue

                slot = _acquire_slot()
                if slot is None:
                    print(f"All slots busy — will retry {m_id} next cycle.")
                    continue   # retry next loop iteration

                session_handled_ids.add(m_id)
                req_profile = db.get_user_profile(requester_email) or profile
                rec_enabled = bool(req_profile.get('bot_recording_enabled', 1))
                db.update_bot_status(m_id, "JOINING",
                                     note=f"[Slot {slot}] Joining {meet_url}")

                t = threading.Thread(
                    target=_run_meeting_in_thread,
                    args=(meet_url, m_id, requester_email, rec_enabled, slot),
                    daemon=True, name=f"LiveSlot-{slot}-{m_id}"
                )
                _active_jobs[m_id] = t
                t.start()
                print(f"▶ [Slot {slot}] Joining {meet_url} for {requester_email}")

            # 3. CALENDAR — scan EVERY connected Google account
            try:
                all_users = db.fetch_all(
                    "SELECT email FROM users "
                    "WHERE google_token IS NOT NULL AND google_token != ''"
                )
            except Exception as e:
                print(f"Could not fetch users: {e}")
                all_users = [{'email': user_email}]

            now = datetime.now(timezone.utc)

            for user_row in all_users:
                cal_email   = user_row['email'] if isinstance(user_row, dict) else user_row[0]
                cal_profile = db.get_user_profile(cal_email) or {}

                if not cal_profile.get('bot_auto_join', 1):
                    continue

                print(f"Checking Calendar for {cal_email}...")
                try:
                    upcoming = get_upcoming_events(user_email=cal_email, max_results=5)
                except Exception as e:
                    print(f"  Calendar error for {cal_email}: {e}")
                    continue

                for event in upcoming:
                    print(f"  [{cal_email}] '{event.get('summary')}' "
                          f"conf={event.get('conferenceData') is not None}")
                    m_id = event.get('id')
                    if m_id in session_handled_ids:
                        continue

                    start_info = event.get('start', {})
                    start_str  = start_info.get('dateTime', start_info.get('date'))
                    start_dt   = parser.parse(start_str)
                    if start_dt.tzinfo is None:
                        start_dt = start_dt.replace(tzinfo=timezone.utc)

                    time_diff     = (now - start_dt).total_seconds() / 60
                    end_info      = event.get('end', {})
                    end_str       = end_info.get('dateTime', end_info.get('date'))
                    meeting_ended = False
                    if end_str:
                        end_dt = parser.parse(end_str)
                        if end_dt.tzinfo is None:
                            end_dt = end_dt.replace(tzinfo=timezone.utc)
                        meeting_ended = now > end_dt
                        print(f"    Time Diff: {time_diff:.1f} min | End: {end_dt} | Ended: {meeting_ended}")
                    else:
                        meeting_ended = now > (start_dt + timedelta(minutes=60))
                        print(f"    Time Diff: {time_diff:.1f} min | No end time, assuming 60 min")

                    if not (-5 <= time_diff <= 60) or meeting_ended:
                        continue

                    # Extract meeting URL
                    meet_url = event.get('hangoutLink')
                    if not meet_url and 'conferenceData' in event:
                        for entry in event['conferenceData'].get('entryPoints', []):
                            if entry.get('type') == 'video':
                                meet_url = entry.get('uri')
                    if not meet_url and 'location' in event:
                        if is_meet_url(event['location']): meet_url = event['location']
                    if not meet_url and 'description' in event:
                        desc = event['description']
                        m = re.search(r'https://meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}', desc)
                        if m: meet_url = m.group(0)
                        if not meet_url:
                            m = re.search(r'https://[a-z0-9.]*zoom\.us/[j|s|my]/[a-zA-Z0-9?=_]*', desc)
                            if m: meet_url = m.group(0)

                    if not meet_url:
                        print(f"    No URL found for '{event.get('summary')}'")
                        continue

                    db_mtg = db.get_meeting(m_id)
                    if db_mtg and db_mtg.get('is_skipped'):
                        print(f"    Skipped by user: {event.get('summary')}")
                        continue

                    slot = _acquire_slot()
                    if slot is None:
                        print(f"    All slots busy — will retry {m_id} next cycle.")
                        continue

                    session_handled_ids.add(m_id)
                    rec_enabled = bool(cal_profile.get('bot_recording_enabled', 1))
                    db.set_meeting_bot_status(m_id, "JOINING", user_email=cal_email,
                                              title=event.get('summary'), start_time=start_str)

                    t = threading.Thread(
                        target=_run_meeting_in_thread,
                        args=(meet_url, m_id, cal_email, rec_enabled, slot),
                        daemon=True, name=f"CalSlot-{slot}-{m_id}"
                    )
                    _active_jobs[m_id] = t
                    t.start()
                    print(f"  ▶ [Slot {slot}] Calendar join '{event.get('summary')}' for {cal_email}")

        except Exception as e:
            print(f"Auto-Pilot loop error: {e}")
            import traceback; traceback.print_exc()

        alive = [tid for tid, t in list(_active_jobs.items()) if t.is_alive()]
        print(f"─ Cycle done. Active: {len(alive)} meetings | Free slots: {sorted(_free_slots)} ─")
        time.sleep(30)

def main():
    import meeting_database as db
    import argparse
    
    parser = argparse.ArgumentParser(description="Renata Meeting Bot")
    parser.add_argument("command", nargs="?", help="URL, --manual, or --autopilot")
    parser.add_argument("--user", help="User email to use for settings and auth")
    args, unknown = parser.parse_known_args()
    
    # 1. Resolve User Context & Preferences
    user_email = args.user
    if not user_email:
        # Fallback to first user in DB if not specified
        # Use fetch_one helper to be compatible with both SQLite and PostgreSQL
        user = db.fetch_one("SELECT email FROM users LIMIT 1")
        user_email = user['email'] if user else "default@rena.ai"

    profile = db.get_user_profile(user_email) or {}
    
    # 2. Extract Managed Settings
    m_bot_name = profile.get('bot_name', 'Rena AI | Meeting Assistant')
    m_audio_dev = profile.get('audio_output_device', 'CABLE Output (VB-Audio Virtual Cable)')
    m_rec_enabled = bool(profile.get('bot_recording_enabled', 1))
    
    # Format Audio Device for FFmpeg
    if "VB-CABLE" in str(m_audio_dev):
        ffmpeg_src = "audio=CABLE Output (VB-Audio Virtual Cable)"
    elif "Default" in str(m_audio_dev):
        ffmpeg_src = "audio=CABLE Output (VB-Audio Virtual Cable)" # Legacy default
    else:
        ffmpeg_src = f"audio={m_audio_dev}"

    command = args.command or (unknown[0] if unknown else None)

    # AUTO-START LOGIC: If no command is given, default to autopilot
    if not command:
        command = "--autopilot"
        print(f"No command provided. AUTO-STARTING in Autopilot mode for: {user_email}")

    bot = RenaMeetingBot(bot_name=m_bot_name, audio_device=ffmpeg_src)
    
    if command == "--manual":
        print(f"Starting Manual Desktop Capture (Device: {m_audio_dev}) for {user_email}")
        bot.record_manual_audio()
    elif command == "--autopilot":
        print(f"Starting Auto-Pilot Mode... Listening for meetings for {user_email}")
        run_auto_pilot(user_email)
    else:
        url = command
        print(f"Joining Meeting: {url} for {user_email}")
        
        if is_meet_url(url):
            bot.join_google_meet(url, record=m_rec_enabled, db=db, user_email=user_email)
        elif is_zoom_url(url):
            bot.join_zoom_meeting(url, record=m_rec_enabled, db=db, user_email=user_email)
        else:
            # Default to Google Meet if unknown but provided as URL
            bot.join_google_meet(url, record=m_rec_enabled, db=db, user_email=user_email)

if __name__ == "__main__":
    main()
