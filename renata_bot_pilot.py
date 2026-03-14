import os
import sys
import time
import subprocess
import signal
import re
import json
import threading
import argparse
import traceback
from pathlib import Path
import sqlite3
from datetime import datetime, timezone, timedelta
from dateutil import parser as dt_parser

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

import meeting_database as db

# The gmail_scanner_service might not be in every environment
try:
    from gmail_scanner_service import gmail_scanner
except ImportError:
    gmail_scanner = None

# --- HELPERS ---
MEET_RE = re.compile(r"meet\.google\.com")
def is_meet_url(text: str) -> bool:
    if not isinstance(text, str):
        return False
    return bool(MEET_RE.search(text))

def is_zoom_url(text: str) -> bool:
    if not isinstance(text, str): 
        return False
    return any(z in text for z in ["zoom.us/j/", "zoom.us/my/", "zoom.us/s/", ".zoom.us/j/"])

def normalize_url(url: str) -> str:
    if not url: 
        return url
    url = url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    return url

# --- BOT CONFIGURATION ---
PERMANENT_BOT_EMAIL = "chandisha.das.fit.cse22@teamfuture.in"
PERMANENT_BOT_PASS = "123Chandisha#"
BOT_SESSION_DIR = os.path.join(os.getcwd(), "bot_session", "main")
os.makedirs(BOT_SESSION_DIR, exist_ok=True)

# --- CALENDAR OPERATIONS ---
def get_service(user_email=None):
    SCOPES = [
        'openid',
        'https://www.googleapis.com/auth/userinfo.profile',
        'https://www.googleapis.com/auth/userinfo.email',
        'https://www.googleapis.com/auth/calendar',
        'https://www.googleapis.com/auth/gmail.readonly',
        'https://www.googleapis.com/auth/gmail.send'
    ]
    if not user_email: 
        user_email = "default@rena.ai"
    
    serialized_token = db.get_user_token(user_email)
    if not serialized_token: 
        return None
        
    try:
        creds_data = json.loads(serialized_token)
        creds = Credentials.from_authorized_user_info(creds_data, SCOPES)
        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
            db.exec_commit(
                "UPDATE users SET google_token = ?, updated_at = CURRENT_TIMESTAMP WHERE email = ?", 
                (creds.to_json(), user_email)
            )
        return build('calendar', 'v3', credentials=creds)
    except Exception: 
        return None

# --- MAIN BOT CLASS ---
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
            except Exception: 
                pass
            
        self.bot_name = bot_name
        self.audio_device = audio_device
        self.output_dir = Path("meeting_outputs") / "recordings"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.audio_process = None
        self.recording_path = None
        self.session_dir = session_dir if session_dir else BOT_SESSION_DIR

    def bot_setup_login(self):
        print(f"Opening Browser for Bot Login to {PERMANENT_BOT_EMAIL}...")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch_persistent_context(
                    self.session_dir, 
                    headless=False, 
                    args=["--start-maximized"]
                )
                page = browser.pages[0]
                page.goto("https://accounts.google.com/")
                print("Waiting for login... Close browser when finished.")
                while True:
                    try:
                        if not browser.is_connected() or len(browser.pages) == 0:
                            break
                        time.sleep(1)
                    except:
                        break
        except Exception as e:
            print(f"Setup Login Error: {e}")
        print("Bot Login Session Saved.")

    def automate_google_login(self, page):
        """Robust automation for Google Login flow."""
        try:
            print(f"Checking Google Login for {PERMANENT_BOT_EMAIL}...")
            
            # If already on accounts page or redirected
            if "accounts.google.com" not in page.url:
                page.goto("https://accounts.google.com/signin", wait_until="networkidle")

            # 1. Check if already logged in by looking for profile info or meet identity
            if "accounts.google.com/v3/signin/identifier" not in page.url and "signin" not in page.url:
                print("Already logged in or on a non-login page.")
                return True

            # 2. Account Chooser / Selector (if multiple accounts exist)
            try:
                email_div = page.locator(f'div[data-email="{PERMANENT_BOT_EMAIL}"], [aria-label*="{PERMANENT_BOT_EMAIL}"]').first
                if email_div.is_visible(timeout=5000):
                    print(f"Selecting existing account: {PERMANENT_BOT_EMAIL}")
                    email_div.click()
                    time.sleep(2)
            except: pass

            # 3. Identifier Field (Email)
            try:
                email_input = page.locator('input[type="email"], #identifierId').first
                if email_input.is_visible(timeout=5000):
                    print(f"Entering email: {PERMANENT_BOT_EMAIL}")
                    email_input.fill(PERMANENT_BOT_EMAIL)
                    page.click('#identifierNext, [jsname="V67oBc"]')
                    time.sleep(3)
            except: pass

            # 4. Handle "Use another account" if needed
            try:
                another = page.locator('text="Use another account"').first
                if another.is_visible(timeout=3000):
                    another.click()
                    time.sleep(2)
            except: pass

            # 5. Password Field
            try:
                pw_field = page.locator('input[type="password"], input[name="password"]').first
                pw_field.wait_for(state="visible", timeout=10000)
                print("Entering password...")
                pw_field.fill(PERMANENT_BOT_PASS)
                page.click('#passwordNext, [jsname="V67oBc"]')
                time.sleep(5)
            except:
                print("Password field not found. Might be already logged in or stuck.")

            # 6. Handle Verification / "Protect your account" / "Continue"
            for _ in range(3):
                try:
                    # Common Google "Continue" or "Not now" buttons after login
                    btns = page.locator('button:has-text("Not now"), button:has-text("Continue"), button:has-text("Done"), button:has-text("I agree")')
                    if btns.count() > 0:
                        print(f"Clicking verification/consent button...")
                        btns.first.click()
                        time.sleep(3)
                    else:
                        break
                except: break

            # 7. Final check
            page.wait_for_load_state("networkidle", timeout=10000)
            success = "accounts.google.com" not in page.url or "myaccount.google.com" in page.url
            print(f"Login success: {success}")
            return success
        except Exception as e: 
            print(f"Auto-login failed: {e}")
            return False

    def start_audio_recording(self, filename):
        self.recording_path = self.output_dir / f"{filename}.wav"
        cmd = [
    "ffmpeg",
    "-threads", "1",
    "-loglevel", "quiet",
    "-y",
    "-f", "dshow",
    "-i", self.audio_device,
    str(self.recording_path)]
        # Use subprocess.CREATE_NEW_PROCESS_GROUP for Windows CTRL+C emulation
        try:
            from subprocess import CREATE_NEW_PROCESS_GROUP
            creation_flags = CREATE_NEW_PROCESS_GROUP
        except ImportError:
            creation_flags = 0
            
        self.audio_process = subprocess.Popen(
            cmd, 
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL, 
            creationflags=creation_flags
        )

    def stop_audio_recording(self):
        if self.audio_process:
            try:
                # Windows Break Event
                from signal import CTRL_BREAK_EVENT
                self.audio_process.send_signal(CTRL_BREAK_EVENT)
            except:
                self.audio_process.terminate()
            self.audio_process.wait()

    def record_manual_audio(self):
        """Standard manual recording from desktop output"""
        self.start_audio_recording(f"Manual_Record_{int(time.time())}")
        print(f"Recording manual audio to {self.recording_path}... Press Ctrl+C to stop.")
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt:
            self.stop_audio_recording()
            print(f"Manual recording saved.")

    def join_zoom_meeting(self, zoom_url, record=True, db_module=None, meeting_id=None, user_email=None):
        if not meeting_id: 
            meeting_id = f"zoom_live_{int(time.time())}"
        
        zoom_url = normalize_url(zoom_url)
        wc_url = zoom_url.replace("/j/", "/wc/join/").replace("/s/", "/wc/join/")
        
        try:
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    self.session_dir,
                    headless=False,
                    viewport=None,
                    args=[
                        "--use-fake-ui-for-media-stream",
                        "--use-fake-device-for-media-stream",
                        "--autoplay-policy=no-user-gesture-required",
                        "--start-maximized",

                        # Optimization flags
                        "--disable-extensions",
                        "--disable-sync",
                        "--disable-background-networking",
                        "--disable-background-timer-throttling",
                        "--disable-renderer-backgrounding",
                        "--disable-component-update",
                        "--disable-default-apps",
                        "--mute-audio",
                        "--no-first-run",
                        "--disable-infobars"
                    ]
                )
                page = context.pages[0]
                Stealth().apply_stealth_sync(page)
                
                if db_module and meeting_id: 
                    db_module.update_bot_status(meeting_id, "FETCHING", "Navigating to Zoom...")
                
                page.goto(wc_url)
                
                try:
                    page.wait_for_selector('input[name="input-name"]', timeout=10000)
                    page.fill('input[name="input-name"]', self.bot_name)
                    page.click('button:has-text("Join")')
                except Exception: 
                    pass
                    
                time.sleep(10)
                
                try:
                    audio_btn = page.locator('button:has-text("Join Audio by Computer")')
                    if audio_btn.count() > 0: 
                        audio_btn.click()
                except Exception: 
                    pass
                
                if db_module and meeting_id: 
                    db_module.update_bot_status(meeting_id, "LIVE", "Renata active in Zoom. Waiting for admission...")
                
                if record: 
                    self.start_audio_recording(f"Zoom_Meeting_{int(time.time())}")
                    
                if db_module and meeting_id:
                    db_module.set_meeting_bot_status(meeting_id, "CONNECTED", user_email=user_email, bot_status_note="Bot joined! Capturing meeting intelligence...")
                
                # Monitor Loop — wait for meeting to end or everyone leaves
                alone_since = None
                ALONE_TIMEOUT_SECS = 60
                while True:
                    try:
                        if page.is_closed():
                            break
                        # If Leave button gone, meeting likely ended
                        has_leave = page.locator('button:has-text("Leave")').count() > 0
                        if not has_leave:
                            if alone_since is None:
                                alone_since = time.time()
                                print("[Zoom Bot] Leave button gone. Will exit in 60s if not restored...")
                            elif (time.time() - alone_since) > ALONE_TIMEOUT_SECS:
                                break
                        else:
                            alone_since = None
                    except Exception:
                        break
                    time.sleep(10)
                
                if record: 
                    self.stop_audio_recording()
                if db_module and meeting_id: 
                    db_module.set_meeting_bot_status(meeting_id, "COMPLETED")
        except Exception as e: 
            print(f"Zoom Error: {e}")

    def join_google_meet(self, meet_url, record=True, db_module=None, meeting_id=None, user_email=None):
        if not meeting_id: 
            meeting_id = f"meet_live_{int(time.time())}"
        
        meet_url = normalize_url(meet_url)
        try:
            with sync_playwright() as p:
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
                
                # PROACTIVE LOGIN: Ensure authenticated before joining
                if not self.automate_google_login(page):
                    print("Warning: Google Login might have failed. Proceeding anyway...")
                
                if db_module and meeting_id: 
                    db_module.update_bot_status(meeting_id, "FETCHING", "Navigating to Google Meet...", user_email=user_email)
                
                page.goto(meet_url)
                page.wait_for_load_state("domcontentloaded")
                
                if db_module and meeting_id: 
                    db_module.update_bot_status(meeting_id, "CONNECTING", "Entering lobby...", user_email=user_email)
                
                # Double check if redirected to login again
                if "accounts.google.com" in page.url:
                    if db_module and meeting_id: 
                        db_module.update_bot_status(meeting_id, "CONNECTING", "Re-authenticating...")
                    self.automate_google_login(page)
                    page.goto(meet_url)
                    time.sleep(5)
                
                # Mute mic/camera shortcuts
                page.keyboard.press("Control+d")
                time.sleep(0.5)
                page.keyboard.press("Control+e")
                time.sleep(1)
                
                # Click Join Button explicitly
                try:
                    btn = page.locator(
                        'button:has-text("Join now"), button:has-text("Ask to join")'
                    ).first
                    btn.wait_for(timeout=8000)
                    btn.click(force=True)
                except:
                    print("Join button not found")
                
                # Wait for Admission
                while True:
                    if page.locator('button[aria-label*="Leave call" i]').count() > 0:
                        if db_module and meeting_id: 
                            db_module.update_bot_status(meeting_id, "CONNECTED", note="Bot joined! Initializing meeting intelligence...", user_email=user_email)
                        break
                    time.sleep(5)
                
                if record: 
                    self.start_audio_recording(f"Meet_{int(time.time())}")
                    
                # Monitor Loop — wait for meeting to end
                alone_since = None
                ALONE_TIMEOUT_SECS = 60  # Leave 60 seconds after everyone else leaves
                CHECK_INTERVAL = 10

                while True:
                    page.wait_for_timeout(CHECK_INTERVAL * 1000)
                    try:
                        if page.is_closed():
                            break
                        if page.locator('text="You left the meeting"').count() > 0:
                            break

                        # ── Participant count ──────────────────────────────────────────
                        # Try multiple selectors that Google Meet uses across versions
                        participant_count = 0
                        for sel in [
                            '[data-participant-id]',           # Classic tile selector
                            '[jsname="r4nke"]',                # Newer participant chip
                            '.VfPpkd-StrnGf-Jh9lGc',          # Participant grid item
                        ]:
                            cnt = page.locator(sel).count()
                            if cnt > 0:
                                participant_count = cnt
                                break

                        # Bot itself counts as 1 — if only 1 (or 0) left, start timer
                        if participant_count <= 1:
                            if alone_since is None:
                                alone_since = time.time()
                                print(f"[Bot] Only bot remains in meeting. Will leave in {ALONE_TIMEOUT_SECS}s...")
                                if db_module and meeting_id:
                                    db_module.update_bot_status(meeting_id, "CONNECTED",
                                        note=f"All participants left. Leaving in {ALONE_TIMEOUT_SECS}s...",
                                        user_email=user_email)
                            elif (time.time() - alone_since) > ALONE_TIMEOUT_SECS:
                                print("[Bot] Timeout reached. Auto-leaving meeting.")
                                # Click Leave call button if it exists
                                try:
                                    leave_btn = page.locator('button[aria-label*="Leave call" i]').first
                                    if leave_btn.count() > 0:
                                        leave_btn.click()
                                        time.sleep(2)
                                except Exception:
                                    pass
                                break
                        else:
                            if alone_since is not None:
                                print("[Bot] Participants rejoined — resetting alone timer.")
                            alone_since = None
                    except Exception:
                        break
                
                self.stop_audio_recording()
                
                if db_module and meeting_id:
                    db_module.update_bot_status(meeting_id, "PROCESSING", note="Meeting ended - Processing...")
                    try:
                        from meeting_notes_generator import process_meeting_audio
                        process_meeting_audio(str(self.recording_path), meeting_id)
                        db_module.update_bot_status(meeting_id, "COMPLETED", note="Report ready")
                    except Exception as ex:
                        print(f"Pipeline Fail: {ex}")
                        db_module.update_bot_status(meeting_id, "FAILED", note="Processing error")
        except Exception as e: 
            print(f"Meet Error: {e}")
            if db_module and meeting_id:
                db_module.update_bot_status(meeting_id, "FAILED", note=f"Meet error: {str(e)[:100]}")

# --- SLOT POOL CONCURRENCY ---
# Optimized for 10+ users and high simultaneous demand
# Each slot uses ~500MB RAM for the browser.
MAX_CONCURRENT_MEETINGS = 20 
_slot_lock   = threading.Lock()
_free_slots  = list(range(MAX_CONCURRENT_MEETINGS))
_active_jobs = {} # meeting_id -> threading.Thread
_active_urls = {} # normalized_url -> meeting_id

def _acquire_slot():
    with _slot_lock:
        if not _free_slots: 
            return None
        return _free_slots.pop(0)

def _release_slot(slot, meeting_id=None, user_email=None, url=None):
    with _slot_lock:
        if slot not in _free_slots:
            _free_slots.append(slot)
            _free_slots.sort()
        if meeting_id:
            _active_jobs.pop((meeting_id, user_email), None)
        if url:
            _active_urls.pop(url, None)

def _get_session_dir(slot):
    return os.path.join(os.getcwd(), "bot_session", f"slot_{slot}")

def _get_audio_device(slot):
    """
    To keep audios separated, each concurrency slot should use a different Virtual Cable.
    Default:
    Slot 0 -> VB-Cable (Standard)
    Slot 1 -> VB-Cable A
    Slot 2 -> VB-Cable B
    Slot 3 -> VB-Cable C (if installed)
    Slot 4 -> VB-Cable D (if installed)
    
    If cables are not installed, it falls back to the main CABLE, 
    meaning audio from multiple meetings will be mixed in one recording.
    """
    if slot == 1: return "audio=CABLE-A Output (VB-Audio Cable A)"
    if slot == 2: return "audio=CABLE-B Output (VB-Audio Cable B)"
    if slot == 3: return "audio=CABLE-C Output (VB-Audio Cable C)"
    if slot == 4: return "audio=CABLE-D Output (VB-Audio Cable D)"
    return "audio=CABLE Output (VB-Audio Virtual Cable)"

def _run_meeting_in_thread(meet_url, meeting_id, user_email, record, slot):
    session_dir = _get_session_dir(slot)
    audio_dev = _get_audio_device(slot)
    norm_url = normalize_url(meet_url)
    
    os.makedirs(session_dir, exist_ok=True)
    
    with _slot_lock:
        _active_urls[norm_url] = meeting_id
        
    try:
        # 1. Update status to JOINING
        db.update_bot_status(meeting_id, "JOINING", note="Bot browser is starting...", user_email=user_email)
        print(f"\n[Slot {slot}] JOINING: {meet_url} for {user_email}")
        
        thread_bot = RenaMeetingBot(user_email=user_email, session_dir=session_dir, audio_device=audio_dev)
        
        if is_meet_url(meet_url):
            thread_bot.join_google_meet(meet_url, record=record, db_module=db, meeting_id=meeting_id, user_email=user_email)
        elif is_zoom_url(meet_url):
            thread_bot.join_zoom_meeting(meet_url, record=record, db_module=db, meeting_id=meeting_id, user_email=user_email)
        else:
            thread_bot.join_google_meet(meet_url, record=record, db_module=db, meeting_id=meeting_id, user_email=user_email)
    except Exception as e:
        print(f"\n[Slot {slot}] FATAL ERROR in thread: {e}")
        traceback.print_exc()
    finally:
        _release_slot(slot, meeting_id=meeting_id, user_email=user_email, url=norm_url)
        print(f"\n[Slot {slot}] RELEASED. Free slots: {sorted(_free_slots)}")

# --- AUTOPILOT LOOP ---
def run_auto_pilot(operator_email):
    print("+--------------------------------------------------+")
    print("| Renata AUTO-PILOT: Concurrent multi-user active  |")
    print(f"| Operator: {operator_email:<38} |")
    print("+--------------------------------------------------+")
    
    session_handled_ids = set()
    
    while True:
        try:
            # 1. LIVE JOIN INTENTS (ALL USERS)
            pending_joins = db.fetch_all("SELECT * FROM meetings WHERE bot_status = 'JOIN_PENDING' ORDER BY created_at ASC")
            for pending in pending_joins:
                m_id = pending['meeting_id']
                u_email = pending.get('user_email', operator_email)
                meet_url = normalize_url(pending['meet_url'])
                
                # PREVENT DUPLICATE JOINS: Check ID, URL, and if currently active
                if (m_id, u_email) in session_handled_ids or (meet_url, u_email) in session_handled_ids:
                    continue
                if (m_id, u_email) in _active_jobs or meet_url in _active_urls:
                    continue
                
                # RECENT CHECK: Only join if the meeting request was created in the last 15 minutes
                try:
                    created_at_str = pending.get('created_at')
                    if created_at_str:
                        if 'T' in created_at_str:
                            c_dt = dt_parser.isoparse(created_at_str)
                        else:
                            c_dt = datetime.strptime(created_at_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                        
                        age_mins = (datetime.now(timezone.utc) - c_dt).total_seconds() / 60
                        if age_mins > 20: 
                            session_handled_ids.add((m_id, u_email))
                            session_handled_ids.add((meet_url, u_email))
                            db.update_bot_status(m_id, "FAILED", note="Skipped: Stale request.", user_email=u_email)
                            continue
                except: pass

                slot = _acquire_slot()
                if slot is not None:
                    _active_jobs[(m_id, u_email)] = True 
                    _active_urls[meet_url] = m_id
                    session_handled_ids.add((m_id, u_email))
                    session_handled_ids.add((meet_url, u_email))
                    
                    db.update_bot_status(m_id, "DISPATCHING", note=f"Slot {slot} acquired. Joining...", user_email=u_email)
                    
                    rec = pending.get('recording_enabled', 1)
                    t = threading.Thread(
                        target=_run_meeting_in_thread, 
                        args=(meet_url, m_id, u_email, rec, slot), 
                        daemon=True
                    )
                    _active_jobs[(m_id, u_email)] = t
                    t.start()

            # 2. CALENDAR SCAN (DISABLED AS PER USER REQUEST - ONLY JOIN ON DISPATCH)
            """
            all_users = db.fetch_all("SELECT email FROM users WHERE google_token IS NOT NULL AND google_token != ''")
            now = datetime.now(timezone.utc)
            
            for user_row in all_users:
                cal_email = user_row['email'] if isinstance(user_row, dict) else user_row[0]
                
                if gmail_scanner: 
                    try:
                        gmail_scanner.scan_inbox(cal_email)
                    except Exception: 
                        pass
                
                service = get_service(cal_email)
                if not service: 
                    continue
                
                try:
                    events = service.events().list(
                        calendarId='primary', 
                        timeMin=now.isoformat().replace('+00:00','Z'), 
                        maxResults=5, 
                        singleEvents=True, 
                        orderBy='startTime'
                    ).execute().get('items', [])
                    
                    for event in events:
                        m_id = event.get('id')
                        url = event.get('hangoutLink')
                        if not url and 'location' in event: 
                            loc = event['location']
                            url = loc if is_meet_url(loc) or is_zoom_url(loc) else None
                        
                        norm_url = normalize_url(url) if url else None
                        
                        if (m_id, cal_email) in session_handled_ids or (norm_url, cal_email) in session_handled_ids or (m_id, cal_email) in _active_jobs: 
                            continue
                        
                        start_str = event.get('start', {}).get('dateTime', event.get('start', {}).get('date'))
                        if not start_str: 
                            continue
                            
                        parsed_dt = dt_parser.parse(start_str)
                        if parsed_dt.tzinfo is None:
                            parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
                            
                        diff = (now - parsed_dt).total_seconds() / 60
                        
                        # Real-time window: started up to 10 mins ago, or starting in next 2 mins
                        if -2 <= diff <= 10:
                            if url:
                                url = normalize_url(url)
                                if (m_id, cal_email) in session_handled_ids or (m_id, cal_email) in _active_jobs or url in _active_urls:
                                    continue
                                    
                                slot = _acquire_slot()
                                if slot is not None:
                                    # MARK ACTIVE IMMEDIATELY
                                    _active_jobs[(m_id, cal_email)] = True
                                    _active_urls[url] = m_id
                                    session_handled_ids.add((m_id, cal_email))
                                    session_handled_ids.add((url, cal_email))
                                    
                                    db.set_meeting_bot_status(m_id, "DISPATCHING", user_email=cal_email, title=event.get('summary'), start_time=start_str, bot_status_note=f"Scheduled event detected. Assigning Slot {slot}...")
                                    
                                    t = threading.Thread(
                                        target=_run_meeting_in_thread, 
                                        args=(url, m_id, cal_email, 1, slot), 
                                        daemon=True
                                    )
                                    _active_jobs[(m_id, cal_email)] = t
                                    t.start()
                except Exception as ex:
                    print(f"Calendar Error for user {cal_email}: {ex}")
            """
            
            time.sleep(5)
            
        except Exception as e:
            if "database" in str(e).lower() or "address" in str(e).lower():
                print(f"Pilot Loop (Network/DB Error): {e}. Retrying in 10s...")
            else:
                print(f"Pilot Loop Error: {e}")
            time.sleep(10)

# --- ENTRY POINT ---
def main():
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("command", nargs="?")
    arg_parser.add_argument("--user")
    args, unknown = arg_parser.parse_known_args()
    
    u_email = args.user
    if not u_email:
        first_user = db.fetch_one("SELECT email FROM users LIMIT 1")
        u_email = first_user['email'] if first_user else "default@rena.ai"
    
    cmd = args.command or (unknown[0] if unknown else "--autopilot")
    
    if cmd == "--autopilot": 
        run_auto_pilot(u_email)
    elif cmd == "--manual": 
        RenaMeetingBot(user_email=u_email).record_manual_audio()
    else:
        bot = RenaMeetingBot(user_email=u_email)
        if is_meet_url(cmd): 
            bot.join_google_meet(cmd, db_module=db, user_email=u_email)
        elif is_zoom_url(cmd): 
            bot.join_zoom_meeting(cmd, db_module=db, user_email=u_email)

if __name__ == "__main__": 
    main()