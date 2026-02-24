import os
import sys
import time
import subprocess
import signal
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

import pyperclip

# --- GOOGLE CALENDAR INTEGRATIONS ---
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# --- HELPERS ---
def is_meet_url(text: str) -> bool:
    if not isinstance(text, str): return False
    return "meet.google.com/" in text

def is_zoom_url(text: str) -> bool:
    if not isinstance(text, str): return False
    return "zoom.us/j/" in text or "zoom.us/my/" in text or "zoom.us/s/" in text or ".zoom.us/j/" in text

# --- GOOGLE SIGN-IN ---
def run_gmail_registration():
    SCOPES = [
        'openid',
        'https://www.googleapis.com/auth/userinfo.profile',
        'https://www.googleapis.com/auth/userinfo.email',
        'https://www.googleapis.com/auth/calendar',
        'https://www.googleapis.com/auth/gmail.readonly',
        'https://www.googleapis.com/auth/gmail.send',
        'https://www.googleapis.com/auth/drive.metadata.readonly'
    ]
    if not os.path.exists('credentials.json'):
        print("❌ Error: credentials.json missing.")
        return "error_missing_json"
    try:
        flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
        
        success_message = "Authentication successful! You can now close this tab and return to your Renata Dashboard which has been unlocked."
        creds = flow.run_local_server(
            port=0, 
            success_message=success_message
        )
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
        return "success"
    except Exception as e:
        return str(e)

# --- CALENDAR OPERATIONS ---
def get_service():
    """Build and return the Calendar service with refreshed credentials."""
    SCOPES = [
        'openid',
        'https://www.googleapis.com/auth/userinfo.profile',
        'https://www.googleapis.com/auth/userinfo.email',
        'https://www.googleapis.com/auth/calendar',
        'https://www.googleapis.com/auth/gmail.readonly',
        'https://www.googleapis.com/auth/gmail.send',
        'https://www.googleapis.com/auth/drive.metadata.readonly'
    ]
    if not os.path.exists('token.json'): return None
    try:
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open('token.json', 'w') as token:
                token.write(creds.to_json())
        return build('calendar', 'v3', credentials=creds)
    except Exception as e:
        print(f"⚠️ Auth/API Error: {e}")
        return None

def get_upcoming_events(max_results=5):
    """Fetches meetings using a clean API call."""
    service = get_service()
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
        print(f"⚠️ Calendar Error: {e}")
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
        print(f"⚠️ User Discovery Error: {e}")
        return None

# --- BOT CONFIGURATION ---
PERMANENT_BOT_EMAIL = "chandisha.das.fit.cse22@teamfuture.in"
BOT_SESSION_DIR = os.path.join(os.getcwd(), "bot_session")

class RenaMeetingBot:
    def __init__(self, bot_name="Rena AI | Meeting Assistant", audio_device="audio=CABLE Output (VB-Audio Virtual Cable)"):
        self.bot_name = bot_name
        self.audio_device = audio_device
        self.output_dir = Path("meeting_outputs") / "recordings"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.audio_process = None
        self.recording_path = None
        self.session_dir = BOT_SESSION_DIR

    def bot_setup_login(self):
        """Hidden feature to allow manual login for the bot's permanent email."""
        print(f"🔧 Opening Browser for Bot Login...")
        print(f"👉 Please log in to {PERMANENT_BOT_EMAIL}")
        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(
                self.session_dir,
                headless=False,
                args=["--start-maximized"]
            )
            page = browser.pages[0]
            page.goto("https://accounts.google.com/")
            print("⏳ Waiting for you to finish login. Close the browser when done.")
            while len(browser.pages) > 0:
                time.sleep(1)
        print("✅ Bot Login Session Saved.")

    def start_audio_recording(self, filename):
        self.recording_path = self.output_dir / f"{filename}.wav"
        # Dynamic device selection
        cmd = ["ffmpeg", "-y", "-f", "dshow", "-i", self.audio_device, str(self.recording_path)]
        self.audio_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)

    def stop_audio_recording(self):
        if self.audio_process:
            self.audio_process.send_signal(signal.CTRL_BREAK_EVENT)
            self.audio_process.wait()

    def join_zoom_meeting(self, zoom_url, record=True, db=None, meeting_id=None):
        """Joins a Zoom meeting via the web client."""
        print(f"🔄 DEBUG: join_zoom_meeting called for {zoom_url}")
        
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
                
                print(f"🚀 Navigating to Zoom Web Client: {wc_url}")
                page.goto(wc_url)
                
                # Wait for name input
                try:
                    page.wait_for_selector('input[name="input-name"]', timeout=10000)
                    page.fill('input[name="input-name"]', self.bot_name)
                    print(f"✍️ Entered bot name: {self.bot_name}")
                    page.click('button:has-text("Join")')
                except:
                    print("⚠️ Name input not found, maybe already joined or cached.")

                # Handle Zoom specifics (Mute/Uncam)
                time.sleep(10) # Wait for join to complete
                
                # Look for "Join Audio by Computer" if it pops up
                try:
                    audio_btn = page.locator('button:has-text("Join Audio by Computer")')
                    if audio_btn.count() > 0:
                        audio_btn.click()
                        print("🎧 Joined audio by computer")
                except: pass

                # Mute & Stop Video
                try:
                    page.keyboard.press("Alt+a") # Mute
                    page.keyboard.press("Alt+v") # Stop Video
                    print("🔇 Muted and Camera OFF (Zoom Shortcuts)")
                except: pass

                if record:
                    # Start recording the local audio output
                    self.start_audio_recording(f"Zoom_Meeting_{int(time.time())}")
                    print(f"🔴 RECORDING STARTED: {self.recording_path}")

                # Keep session alive
                print("🏁 Zoom Session LIVE. Monitoring for exit...")
                if db and meeting_id:
                    db.set_meeting_bot_status(meeting_id, "CONNECTED")
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
            print(f"❌ Zoom Error: {e}")

    def join_google_meet(self, meet_url, record=True, db=None, meeting_id=None):
        print(f"🔄 DEBUG: join_google_meet called for {meet_url}")
        try:
            with sync_playwright() as p:
                # ... (existing setup) ...
                print("🔄 DEBUG: Launching Browser Context...")
                context = p.chromium.launch_persistent_context(
                    self.session_dir,
                    headless=False,
                    args=[
                        "--use-fake-ui-for-media-stream",
                        "--use-fake-device-for-media-stream",
                        "--autoplay-policy=no-user-gesture-required",
                        "--disable-blink-features=AutomationControlled",
                        "--start-maximized",
                        "--disable-notifications"
                    ]
                )
                page = context.pages[0]
                Stealth().apply_stealth_sync(page)
                
                print(f"🚀 DEBUG: Navigating to {meet_url}")
                page.goto(meet_url)
                time.sleep(5)

                # ... (login check, mute, join click logic same as before) ...
                # Check if login is required (redirected to accounts.google.com)
                if "accounts.google.com" in page.url:
                    print("⚠️ DEBUG: Bot needs to sign in! Waiting for user...")
                    time.sleep(10) # Give some time, but this needs manual intervention mostly

                # Dismiss any camera/microphone error dialogs
                print("🔄 DEBUG: Dismissing any permission dialogs...")
                try:
                    # Close "Camera not found" or similar error dialogs
                    close_btns = page.locator('button[aria-label="Dismiss"], button:has-text("Got it"), button:has-text("Dismiss")').all()
                    for btn in close_btns:
                        try:
                            btn.click(timeout=1000)
                            print("✅ Dismissed error dialog")
                        except: pass
                except: pass

                # Mute Mic & Camera (Multiple Methods for Reliability)
                print("🔄 DEBUG: Ensuring mic and camera are OFF...")
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
                            print("✅ Turned OFF microphone")
                    except: pass
                    
                    try:
                        # Look for "Turn off camera" button (means it's ON, so click to turn OFF)
                        cam_on_btn = page.locator('button[aria-label*="Turn off camera" i]').first
                        if cam_on_btn.count() > 0:
                            cam_on_btn.click()
                            print("✅ Turned OFF camera")
                    except: pass
                    
                    print("✅ DEBUG: Mic and camera are OFF")
                except Exception as e:
                    print(f"⚠️ DEBUG: Mute operation: {e}")

                # Auto-click "Ask to join" or "Join now" button
                print("🔄 DEBUG: Looking for Join button...")
                time.sleep(2)
                try:
                    # Try multiple selectors for reliability
                    join_selectors = [
                        'span:has-text("Ask to join")',
                        'span:has-text("Join now")',
                        'button:has-text("Ask to join")',
                        'button:has-text("Join now")',
                        'div[role="button"]:has-text("Ask to join")',
                        'div[role="button"]:has-text("Join now")'
                    ]
                    
                    clicked = False
                    for selector in join_selectors:
                        try:
                            btn = page.locator(selector).first
                            if btn.count() > 0:
                                btn.click()
                                print(f"✅ DEBUG: Clicked join button: {selector}")
                                clicked = True
                                break
                        except: continue
                    
                    if not clicked:
                        print("⚠️ DEBUG: Join button not found with standard selectors, trying fallback...")
                        page.click('button:has-text("Join")', timeout=2000)
                        
                except Exception as e: 
                    print(f"❌ DEBUG: Join click failed: {e}")

                # Wait for Admission
                print("⏳ Waiting in lobby (infinite loop until admitted)...")
                try:
                    # Look for clues that we are in the meeting
                    # 1. "You're waiting to be admitted" text
                    # 2. Meeting control bar appearing
                    # 3. List of participants
                    while True:
                        if page.locator('button[aria-label*="Leave call" i], button[aria-label*="Leave meeting" i]').count() > 0:
                            print("🎉 Admitted to Google Meet!")
                            if db and meeting_id: 
                                db.set_meeting_bot_status(meeting_id, "CONNECTED")
                                db.update_meeting_bot_note(meeting_id, "Recording active")
                            break
                        
                        # Check for "Someone will let you in soon"
                        if page.locator('span:has-text("Someone will let you in soon"), div:has-text("You\'re waiting to be admitted")').count() > 0:
                            if db and meeting_id: db.update_meeting_bot_note(meeting_id, "In Lobby - Waiting for host")
                        
                        time.sleep(5)
                except Exception as e:
                    print(f"⚠️ Lobby wait error: {e}")

                if record:
                    # Start recording the local audio output
                    self.start_audio_recording(f"Meet_Meeting_{int(time.time())}")
                    print(f"🔴 RECORDING STARTED: {self.recording_path}")
                
                # Smart Meeting Monitor - Auto-leave when meeting ends
                print("👀 Monitoring meeting status...")
                start_monitor = time.time()
                alone_since = None  # Track when bot became alone
                
                while True:
                    time.sleep(5)
                    try:
                        # Check 1: Browser closed
                        if page.is_closed(): 
                            print("❌ Browser closed.")
                            break
                        
                        # Check 2: "You left" screen
                        if page.locator('text="You left the meeting"').count() > 0 or \
                           page.locator('text="Return to home screen"').count() > 0:
                            print("✅ Meeting ended (detected exit screen).")
                            break
                        
                        # Check 3: URL changed to home
                        if "meet.google.com" in page.url and len(page.url.split('/')) <= 3:
                            print("✅ Meeting ended (returned to home).")
                            break
                        
                        # Check 4: Participant count - auto-leave if alone for 5 mins
                        try:
                            # Try to count participants in the meeting
                            participant_elements = page.locator('[data-participant-id]').count()
                            
                            if participant_elements <= 1:  # Only bot remains
                                if alone_since is None:
                                    alone_since = time.time()
                                    print("⚠️ Bot is alone in meeting. Will auto-leave in 5 mins if no one joins...")
                                else:
                                    alone_duration = (time.time() - alone_since) / 60
                                    if alone_duration >= 5:
                                        print("🚪 Auto-leaving: Bot alone for 5+ minutes.")
                                        # Click leave button
                                        try:
                                            page.click('button[aria-label="Leave call"]', timeout=3000)
                                        except: pass
                                        break
                            else:
                                # Reset alone timer if others join
                                if alone_since is not None:
                                    print("✅ Others joined, continuing meeting...")
                                alone_since = None
                        except:
                            pass  # Participant count check failed, continue monitoring
                            
                    except Exception as e:
                        print(f"⚠️ Monitor error: {e}")
                        break

            # MEETING ENDED - CLEANUP & PIPELINE
            print("🛑 Meeting Finished. Stopping recording...")
            self.stop_audio_recording()
            
            # TRIGGER PIPELINE with detailed logging
            if db and meeting_id and self.recording_path and os.path.exists(self.recording_path):
                print("=" * 60)
                print("🚀 POST-MEETING PIPELINE ACTIVATED")
                print("=" * 60)
                db.set_meeting_bot_status(meeting_id, "PROCESSING", status_note="Meeting ended - Generating PDF...")
                
                try:
                    # Import and run the generator directly for better logging
                    print(f"📁 Audio File: {self.recording_path}")
                    print("🎙️ Stage 1/2: Running Gemini 3 Flash (Transcription + Diarization)...")
                    
                    import meeting_notes_generator
                    generator = meeting_notes_generator.AdaptiveMeetingNotesGenerator(
                        audio_path=str(self.recording_path)
                    )
                    
                    generator.transcribe_audio()
                    
                    print("🧠 Stage 2/2: Generating AI Summary, MOM & Action Plans...")
                    generator.generate_summary()
                    
                    print("📄 Exporting PDF & JSON Reports...")
                    generator.export_to_pdf()
                    generator.export_to_json()
                    
                    # NEW: Save all intelligence back to the database for Analytics/Dashboard
                    print("🗄️ Saving results to database...")
                    db.save_meeting_results(
                        meeting_id=meeting_id,
                        transcript=json.dumps(generator.structured_transcript),
                        summary=generator.intel.get('summary_en', ''),
                        action_items=generator.intel.get('actions', []),
                        speaker_stats=generator.intel.get('speaker_analytics', {}),
                        engagement=generator.intel.get('engagement_metrics', {})
                    )
                    
                    print("=" * 60)
                    print("✅ PIPELINE COMPLETE!")
                    print("=" * 60)
                    
                    # Update database with results
                    db.set_meeting_bot_status(meeting_id, "COMPLETED", status_note="Report ready")
                    
                except Exception as e:
                    print(f"❌ Pipeline Failed: {e}")
                    import traceback
                    traceback.print_exc()
                    db.set_meeting_bot_status(meeting_id, "FAILED", status_note="Processing failed - Check logs")
        except Exception as e:
            print(f"❌ FATAL ERROR in join_google_meet: {e}")
            import traceback
            traceback.print_exc()

    def record_manual_audio(self):
        # Create folder with unique ID
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        manual_recording_dir = self.output_dir / f"manual_{timestamp}"
        manual_recording_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"🎙️ Manual Recording Started. Saving to {manual_recording_dir}")
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
    Main background loop for Renata.
    """
    import meeting_database as db
    from gmail_scanner_service import gmail_scanner
    from dateutil import parser
    
    print(f"🤖 Renata Auto-Pilot Active for {user_email}")
    bot = RenaMeetingBot()
    joined_meetings = set() # Track IDs joined in this session

    while True:
        try:
            profile = db.get_user_profile(user_email)
            if not profile:
                time.sleep(60)
                continue

            # 1. SCAN GMAIL
            print("📩 Scanning Gmail...")
            gmail_scanner.scan_inbox(user_email)

            # 2. CHECK CALENDAR
            if profile.get('bot_auto_join', 1):
                print("📅 Checking Calendar...")
                upcoming = get_upcoming_events(max_results=5)
                now = datetime.now(timezone.utc)

                for event in upcoming:
                    print(f"🔎 DEBUG: Found '{event.get('summary')}' | Status: {event.get('status')} | Conf: {event.get('conferenceData') is not None}")
                    m_id = event.get('id')
                    if m_id in joined_meetings: continue

                    # Parse Time
                    start_info = event.get('start', {})
                    start_str = start_info.get('dateTime', start_info.get('date'))
                    start_dt = parser.parse(start_str)
                    if start_dt.tzinfo is None:
                        start_dt = start_dt.replace(tzinfo=timezone.utc)

                    # Smart Join Window Logic:
                    # - Join if meeting starts in next 5 mins (upcoming)
                    # - Join if meeting started within last 60 mins AND hasn't ended yet (ongoing)
                    time_diff = (now - start_dt).total_seconds() / 60
                    print(f"⏰ Time Diff: {time_diff:.2f} mins | Start: {start_dt}")
                    
                    # Check if meeting has ended
                    end_info = event.get('end', {})
                    end_str = end_info.get('dateTime', end_info.get('date'))
                    meeting_ended = False
                    if end_str:
                        end_dt = parser.parse(end_str)
                        if end_dt.tzinfo is None:
                            end_dt = end_dt.replace(tzinfo=timezone.utc)
                        meeting_ended = now > end_dt
                        print(f"📅 End Time: {end_dt} | Meeting Ended: {meeting_ended}")
                    else:
                        # No end time provided - assume default 60 min duration
                        assumed_end = start_dt + timedelta(minutes=60)
                        meeting_ended = now > assumed_end
                        print(f"⚠️ No end time in event, assuming 60min duration | Assumed End: {assumed_end} | Meeting Ended: {meeting_ended}")
                    
                    # Only join if:
                    # 1. Meeting starts within 5 mins OR started within last 60 mins
                    # 2. Meeting has NOT ended yet
                    if -5 <= time_diff <= 60 and not meeting_ended:
                        meet_url = event.get('hangoutLink')
                        
                        if not meet_url and 'conferenceData' in event:
                            for entry in event['conferenceData'].get('entryPoints', []):
                                if entry.get('type') == 'video': 
                                    meet_url = entry.get('uri')
                        
                        if not meet_url and 'location' in event:
                            if is_meet_url(event['location']): meet_url = event['location'] # type: ignore
                            
                        # Last resort: Check description for links
                        if not meet_url and 'description' in event:
                            desc = event['description']
                            # Simple regex for meet.google.com
                            meet_match = re.search(r'https://meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}', desc)
                            if meet_match:
                                meet_url = meet_match.group(0)
                            
                            # Regex for Zoom
                            if not meet_url:
                                zoom_match = re.search(r'https://[a-z0-9.]*zoom\.us/[j|s|my]/[a-zA-Z0-9?=_]*', desc)
                                if zoom_match:
                                    meet_url = zoom_match.group(0)
                        
                        print(f"🔗 Extracted URL: {meet_url}")
                        
                        if not meet_url:
                            print(f"⚠️ DEBUG: FULL EVENT DUMP: {event}")
                        
                        if meet_url:
                            # Check if skipped in DB
                            db_meeting = db.get_meeting(m_id)
                            if db_meeting and db_meeting.get('is_skipped'):
                                print(f"⏭️ Skipping '{event.get('summary')}' (User cancelled).")
                                continue
                            
                            print(f"🚀 Joining Meeting: {event.get('summary')} at {meet_url}")
                            # Record preference from profile
                            rec_enabled = profile.get('bot_recording_enabled', 1)
                            
                            # Update status for UI feedback
                            db.set_meeting_bot_status(m_id, "JOINING")
                            
                            # CRITICAL: Join!
                            if is_meet_url(meet_url):
                                bot.join_google_meet(meet_url, record=rec_enabled, db=db, meeting_id=m_id)
                            elif is_zoom_url(meet_url):
                                bot.join_zoom_meeting(meet_url, record=rec_enabled, db=db, meeting_id=m_id)
                            else:
                                print(f"⚠️ Unknown meeting type for URL: {meet_url}")
                            
                            # Note: Status is now updated INSIDE join_google_meet upon admission
                            joined_meetings.add(m_id)
            
            # Wait 30 seconds for aggressive detection
            time.sleep(30) 
        except Exception as e:
            print(f"⚠️ Auto-Pilot Error: {e}")
            time.sleep(60)

def main():
    import meeting_database as db
    
    # 1. Resolve User Context & Preferences
    user_info = get_user_info() or {}
    user_email = user_info.get('email', "default@rena.ai")
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

    if len(sys.argv) > 1:
        bot = RenaMeetingBot(bot_name=m_bot_name, audio_device=ffmpeg_src)
        
        if sys.argv[1] == "--manual":
            print(f"🚀 Starting Manual Desktop Capture (Device: {m_audio_dev})")
            bot.record_manual_audio()
        elif sys.argv[1] == "--autopilot":
            run_auto_pilot(user_email)
        else:
            url = sys.argv[1]
            bot.join_google_meet(url, record=m_rec_enabled)
    else:
        print("Usage: python renata_bot_pilot.py [URL], --manual, or --autopilot")

if __name__ == "__main__":
    main()
