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
from dotenv import load_dotenv

load_dotenv(override=True)

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
PERMANENT_BOT_EMAIL = os.getenv("BOT_EMAIL", "renata@renataiot.com")
PERMANENT_BOT_PASS = os.getenv("BOT_PASSWORD", "")
BOT_SESSION_DIR = os.path.join(os.getcwd(), "bot_session", "main")
os.makedirs(BOT_SESSION_DIR, exist_ok=True)

if not PERMANENT_BOT_PASS:
    print("⚠ WARNING: BOT_PASSWORD not set in .env! Google login will fail.")
    print("  Add to .env:  BOT_EMAIL=renata@renataiot.com")
    print("                BOT_PASSWORD=your_password_here")


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
        """Session-first login: reuse saved session, only do full login if needed."""
        try:
            if not PERMANENT_BOT_EMAIL or not PERMANENT_BOT_PASS:
                print("[Login] ERROR: BOT_EMAIL or BOT_PASSWORD not set in .env!")
                return False

            print(f"[Login] Checking session for {PERMANENT_BOT_EMAIL}...")

            # Quick session check — see if already logged in
            page.goto("https://myaccount.google.com/", wait_until="networkidle", timeout=20000)
            time.sleep(2)

            if "myaccount.google.com" in page.url:
                page_text = page.content().lower()
                if PERMANENT_BOT_EMAIL.lower() in page_text:
                    print(f"[Login] ✓ Session valid - already signed in as {PERMANENT_BOT_EMAIL}")
                    return True
                else:
                    print(f"[Login] Wrong account detected. Logging out...")
                    page.goto("https://accounts.google.com/Logout", wait_until="networkidle", timeout=15000)
                    time.sleep(2)

            # Need to sign in
            print(f"[Login] Signing in as {PERMANENT_BOT_EMAIL}...")
            page.goto("https://accounts.google.com/signin", wait_until="networkidle", timeout=20000)
            time.sleep(3)

            # Handle account chooser tile
            try:
                email_tile = page.locator(f'div[data-email="{PERMANENT_BOT_EMAIL}"]').first
                if email_tile.is_visible(timeout=3000):
                    print(f"[Login] Selecting account tile: {PERMANENT_BOT_EMAIL}")
                    email_tile.click()
                    time.sleep(3)
                    try:
                        pw = page.locator('input[type="password"]').first
                        if pw.is_visible(timeout=5000):
                            pw.fill(PERMANENT_BOT_PASS)
                            page.locator('#passwordNext button').first.click()
                            time.sleep(5)
                    except: pass
                    self._handle_post_login(page)
                    self._wait_for_2fa(page)
                    return self._verify_login(page)
            except: pass

            # Click "Use another account" if shown
            try:
                another = page.locator('text="Use another account"').first
                if another.is_visible(timeout=2000):
                    another.click()
                    time.sleep(3)
            except: pass

            # Enter email
            try:
                email_input = page.locator('#identifierId').first
                email_input.wait_for(state="visible", timeout=10000)
                print(f"[Login] Entering email: {PERMANENT_BOT_EMAIL}")
                email_input.fill(PERMANENT_BOT_EMAIL)
                page.locator('#identifierNext button').first.click()
                time.sleep(4)
            except Exception as e:
                print(f"[Login] Email step error: {e}")

            # Enter password
            try:
                pw_field = page.locator('input[type="password"]').first
                pw_field.wait_for(state="visible", timeout=15000)
                print("[Login] Entering password...")
                pw_field.fill(PERMANENT_BOT_PASS)
                page.locator('#passwordNext button').first.click()
                time.sleep(5)
            except Exception as e:
                print(f"[Login] Password step error: {e}")

            # Handle consent screens + 2FA
            self._handle_post_login(page)
            self._wait_for_2fa(page)
            return self._verify_login(page)
        except Exception as e:
            print(f"[Login] Error: {e}")
            return False

    def _wait_for_2fa(self, page):
        """If 2FA challenge is shown, wait up to 60s for manual approval."""
        time.sleep(2)
        url = page.url.lower()
        if "challenge" in url or "signin/v2" in url or "interstitial" in url:
            print("[Login] ⚠ 2FA verification required! Waiting 60s for manual approval...")
            print("[Login]   -> Please approve on your phone or enter the code.")
            for i in range(12):
                time.sleep(5)
                current = page.url.lower()
                if "myaccount" in current or ("accounts.google.com" not in current and "challenge" not in current):
                    print("[Login] ✓ 2FA approved!")
                    return
            print("[Login] ⚠ 2FA timeout - proceeding anyway...")

    def _verify_login(self, page):
        """Verify correct account is signed in."""
        try:
            page.goto("https://myaccount.google.com/", wait_until="networkidle", timeout=15000)
            time.sleep(2)
            if "myaccount.google.com" in page.url:
                if PERMANENT_BOT_EMAIL.lower() in page.content().lower():
                    print(f"[Login] ✓ Verified: signed in as {PERMANENT_BOT_EMAIL}")
                    return True
            print("[Login] ⚠ Could not verify login.")
            return False
        except:
            return False

    def _handle_post_login(self, page):
        """Handle Google's post-login verification/consent screens."""
        for _ in range(5):
            try:
                btns = page.locator('button:has-text("Not now"), button:has-text("Continue"), button:has-text("Done"), button:has-text("I agree"), button:has-text("Next")')
                if btns.count() > 0:
                    print(f"[Login] Clicking consent button...")
                    btns.first.click()
                    time.sleep(3)
                else:
                    break
            except: break



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
                ALONE_TIMEOUT_SECS = 30
                while True:
                    try:
                        if page.is_closed():
                            break
                        # Check for user cancellation
                        if db_module and meeting_id:
                            status_data = db_module.fetch_one("SELECT bot_status FROM meetings WHERE meeting_id = ?", (meeting_id,))
                            if status_data and status_data.get('bot_status') == 'CANCELED':
                                print(f"[Zoom Bot] Cancellation requested for {meeting_id}. Leaving...")
                                break
                        
                        # If Leave button gone, meeting likely ended
                        has_leave = page.locator('button:has-text("Leave")').count() > 0
                        if not has_leave:
                            if alone_since is None:
                                alone_since = time.time()
                                print("[Zoom Bot] Leave button gone. Will exit in 30s if not restored...")
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
                    db_module.update_bot_status(meeting_id, "PROCESSING", note="Meeting ended - Processing...")
                    try:
                        from meeting_notes_generator import process_meeting_audio
                        process_meeting_audio(str(self.recording_path), meeting_id)
                        db_module.update_bot_status(meeting_id, "COMPLETED", note="Report ready")
                    except Exception as ex:
                        print(f"Zoom Pipeline Fail: {ex}")
                        db_module.update_bot_status(meeting_id, "FAILED", note="Processing error")
        except Exception as e: 
            print(f"Zoom Error: {e}")
            if db_module and meeting_id:
                db_module.update_bot_status(meeting_id, "FAILED", note=f"Zoom error: {str(e)[:100]}")

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
                time.sleep(3)
                
                if db_module and meeting_id: 
                    db_module.update_bot_status(meeting_id, "CONNECTING", "Entering lobby...", user_email=user_email)
                
                # Double check if redirected to login again
                if "accounts.google.com" in page.url:
                    if db_module and meeting_id: 
                        db_module.update_bot_status(meeting_id, "CONNECTING", "Re-authenticating...")
                    self.automate_google_login(page)
                    page.goto(meet_url)
                    time.sleep(5)
                
                # Handle "You can't join this video call" by clearing session and re-logging
                try:
                    cant_join = page.locator('text="You can\'t join this video call"')
                    if cant_join.count() > 0:
                        print("[Meet] 'You can't join' detected! Clearing stale session and re-authenticating...")
                        if db_module and meeting_id:
                            db_module.update_bot_status(meeting_id, "CONNECTING", "Re-authenticating with correct account...", user_email=user_email)
                        # Clear stale session cookies
                        context.clear_cookies()
                        # Re-login
                        self.automate_google_login(page)
                        # Retry navigation
                        page.goto(meet_url)
                        page.wait_for_load_state("domcontentloaded")
                        time.sleep(5)
                except: pass

                
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
                ALONE_TIMEOUT_SECS = 30  # Leave 30 seconds after everyone else leaves
                CHECK_INTERVAL = 10

                while True:
                    page.wait_for_timeout(CHECK_INTERVAL * 1000)
                    try:
                        if page.is_closed():
                            break
                        if page.locator('text="You left the meeting"').count() > 0:
                            break
                        
                        # --- Live AI Note Taking Logic ---
                        if not hasattr(self, '_last_notes_sync'):
                            self._last_notes_sync = time.time()
                            self._captured_lines = []
                            # Enable Captions
                            page.keyboard.press("c")
                            print("[Live] AI Note-taking: Captions enabled.")

                        # Scrape Live Captions (if visible)
                        try:
                            # Standard Google Meet caption selector
                            elements = page.locator('div[jscontroller="p2V79"] div[role="log"] span, div.Vwo7of span').all_text_contents()
                            if elements:
                                chunk = " ".join(elements).strip()
                                if chunk and (not self._captured_lines or chunk != self._captured_lines[-1]):
                                    self._captured_lines.append(chunk)
                        except: pass

                        # Sync every 120 seconds
                        if time.time() - self._last_notes_sync > 120:
                            if len(self._captured_lines) > 3:
                                try:
                                    print("[Live] AI Note-taking: Synchronizing insights with Gemini 3.0...")
                                    full_text = "\n".join(self._captured_lines[-50:])
                                    prompt = ("The following are live meeting transcripts. Extract Key Decisions, Action Items, and main Discussion Points as of now. "
                                             "Be professional and use a structured bulleted format. Focus on 'Minutes of Meeting' style.\n\n"
                                             f"TRANSCRIPT:\n{full_text}")
                                    
                                    # Use Gemini 3.0 Flash Priority
                                    api_key = os.getenv("GEMINI_API_KEY")
                                    insights = None
                                    if api_key:
                                        try:
                                            import google.generativeai as genai
                                            genai.configure(api_key=api_key)
                                            # Priority: 3.0 -> 2.5
                                            for model_id in ["gemini-3-flash-preview", "gemini-2.5-flash-preview"]:
                                                try:
                                                    model = genai.GenerativeModel(model_id)
                                                    resp = model.generate_content(prompt)
                                                    insights = resp.text
                                                    if insights: break
                                                except: continue
                                        except: pass
                                    
                                    if insights:
                                        db_module.update_bot_status(meeting_id, "CONNECTED", note=f"LIVE_INSIGHTS:\n{insights}", user_email=user_email)
                                except Exception as n_err:
                                    print(f"[Live] Sync Error: {n_err}")
                            self._last_notes_sync = time.time()

                        # Check for user cancellation
                        if db_module and meeting_id:
                            # Re-fetch from DB directly since we need fresh status
                            status_data = db_module.fetch_all("SELECT bot_status FROM meetings WHERE meeting_id = ?", (meeting_id,))
                            if status_data and status_data[0].get('bot_status') == 'CANCELED':
                                print(f"[Google Meet Bot] Cancellation requested for {meeting_id}. Leaving...")
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
    # Fetch all users with active integrations
    integrated_users = db.fetch_all("SELECT email FROM users WHERE google_token IS NOT NULL OR zoom_token IS NOT NULL")
    user_emails = [u['email'] for u in integrated_users]
    if not user_emails:
        user_emails = [operator_email]
    
    print("+--------------------------------------------------+")
    print("| Renata AUTO-PILOT: Concurrent multi-user active  |")
    print(f"| Integrated Users:                                |")
    for email in user_emails:
        print(f"| - {email:<46} |")
    print("+--------------------------------------------------+")
    PILOT_BOOT_TIME = datetime.now(timezone.utc)
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
                        
                        # IGNORE STALE REQUESTS: Skip if older than 5 mins OR created before this bot instance started
                        if age_mins > 5 or c_dt < (PILOT_BOOT_TIME - timedelta(seconds=10)): 
                            session_handled_ids.add((m_id, u_email))
                            session_handled_ids.add((meet_url, u_email))
                            # Don't mark as FAILED if it was just an old one from a previous run
                            if age_mins > 30:
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

            # 2. CALENDAR SCAN (Auto-join if enabled by user)
            all_users = db.fetch_all("SELECT email, bot_auto_join FROM users WHERE (google_token IS NOT NULL AND google_token != '')")
            now = datetime.now(timezone.utc)
            
            for user_row in all_users:
                cal_email = user_row['email']
                # Respect auto-join setting
                if not user_row.get('bot_auto_join', 1):
                    continue
                
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
                        timeMin=(now - timedelta(minutes=5)).isoformat().replace('+00:00','Z'), 
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
                        
                        # Real-time window: Join ONLY if started (diff >= 0) and within 15 mins (ongoing)
                        if 0 <= diff <= 15:
                            if url:
                                url = normalize_url(url)
                                
                                # Check if user manually skipped this specific meeting
                                db_meeting = db.fetch_one("SELECT is_skipped FROM meetings WHERE meeting_id = ? AND user_email = ?", (m_id, cal_email))
                                if db_meeting and db_meeting.get('is_skipped', 0):
                                    if (m_id, cal_email) not in session_handled_ids:
                                        print(f"[Pilot] Meeting {m_id} skipped by user preference for {cal_email}")
                                        session_handled_ids.add((m_id, cal_email))
                                    continue

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