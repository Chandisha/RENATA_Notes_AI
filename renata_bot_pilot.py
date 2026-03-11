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
from datetime import datetime, timezone, timedelta
from dateutil import parser as dt_parser

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

import meeting_database as db
# The gmail_scanner_service might not be in every environment, so we catch its import
try:
    from gmail_scanner_service import gmail_scanner
except ImportError:
    gmail_scanner = None

# --- HELPERS ---
def is_meet_url(text: str) -> bool:
    if not isinstance(text, str): return False
    return "meet.google.com/" in text

def is_zoom_url(text: str) -> bool:
    if not isinstance(text, str): return False
    return "zoom.us/j/" in text or "zoom.us/my/" in text or "zoom.us/s/" in text or ".zoom.us/j/" in text

def normalize_url(url: str) -> str:
    if not url: return url
    url = url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    return url

# --- SLOT POOL CONFIGURATION ---
MAX_CONCURRENT_MEETINGS = 3 # One PC can handle 3 meetings at once
_slot_lock   = threading.Lock()
_free_slots  = list(range(MAX_CONCURRENT_MEETINGS))
_active_jobs = {} # meeting_id -> threading.Thread

def _acquire_slot():
    with _slot_lock:
        if not _free_slots: return None
        return _free_slots.pop(0)

def _release_slot(slot):
    with _slot_lock:
        if slot not in _free_slots:
            _free_slots.append(slot)
            _free_slots.sort()

def _get_session_dir(slot):
    if slot == 0: return os.path.join(os.getcwd(), "bot_session")
    return os.path.join(os.getcwd(), f"bot_session/slot_{slot}")

def _run_meeting_in_thread(meet_url, meeting_id, user_email, record, slot):
    session_dir = _get_session_dir(slot)
    os.makedirs(session_dir, exist_ok=True)
    try:
        print(f"\n[Slot {slot}] STARTING: {meet_url} for {user_email} (ID: {meeting_id})")
        thread_bot = RenaMeetingBot(user_email=user_email, session_dir=session_dir)
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
        _active_jobs.pop(meeting_id, None)
        _release_slot(slot)
        print(f"\n[Slot {slot}] RELEASED. Free slots: {sorted(_free_slots)}")

# --- BOT CONFIGURATION ---
PERMANENT_BOT_EMAIL = "chandisha.das.fit.cse22@teamfuture.in"
PERMANENT_BOT_PASS = "123Chandisha#"
BOT_SESSION_DIR = os.path.join(os.getcwd(), "bot_session")

# --- CALENDAR OPERATIONS ---
def get_service(user_email=None):
    SCOPES = ['openid','https://www.googleapis.com/auth/userinfo.profile','https://www.googleapis.com/auth/userinfo.email','https://www.googleapis.com/auth/calendar','https://www.googleapis.com/auth/gmail.readonly','https://www.googleapis.com/auth/gmail.send']
    if not user_email: user_email = "default@rena.ai"
    serialized_token = db.get_user_token(user_email)
    if not serialized_token: return None
    try:
        creds_data = json.loads(serialized_token)
        creds = Credentials.from_authorized_user_info(creds_data, SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            db.exec_commit("UPDATE users SET google_token = ?, updated_at = CURRENT_TIMESTAMP WHERE email = ?", (creds.to_json(), user_email))
        return build('calendar', 'v3', credentials=creds)
    except: return None

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
            
        self.bot_name = bot_name
        self.audio_device = audio_device
        self.output_dir = Path("meeting_outputs") / "recordings"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.audio_process = None
        self.recording_path = None
        self.session_dir = session_dir if session_dir else BOT_SESSION_DIR

    def bot_setup_login(self):
        print(f"Opening Browser for Bot Login to {PERMANENT_BOT_EMAIL}...")
        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(self.session_dir, headless=False, args=["--start-maximized"])
            page = browser.pages[0]; page.goto("https://accounts.google.com/")
            while len(browser.pages) > 0: time.sleep(1)
        print("Bot Login Session Saved.")

    def automate_google_login(self, page):
        try:
            if "AccountChooser" in page.url or page.locator(f'div[data-email="{PERMANENT_BOT_EMAIL}"]').count() > 0:
                page.click(f'div[data-email="{PERMANENT_BOT_EMAIL}"]')
                time.sleep(2)
            if page.locator('input[type="email"]').is_visible(timeout=5000):
                page.fill('input[type="email"]', PERMANENT_BOT_EMAIL)
                page.click('#identifierNext'); time.sleep(2)
            pw_field = page.locator('input[type="password"]')
            pw_field.wait_for(state="visible", timeout=10000)
            pw_field.fill(PERMANENT_BOT_PASS); page.click('#passwordNext')
            time.sleep(5)
            return "accounts.google.com" not in page.url
        except: return False

    def start_audio_recording(self, filename):
        self.recording_path = self.output_dir / f"{filename}.wav"
        cmd = ["ffmpeg", "-y", "-f", "dshow", "-i", self.audio_device, str(self.recording_path)]
        self.audio_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)

    def stop_audio_recording(self):
        if self.audio_process:
            self.audio_process.send_signal(signal.CTRL_BREAK_EVENT)
            self.audio_process.wait()

    def join_zoom_meeting(self, zoom_url, record=True, db_module=None, meeting_id=None, user_email=None):
        if not meeting_id: meeting_id = f"zoom_live_{int(time.time())}"
        zoom_url = normalize_url(zoom_url)
        wc_url = zoom_url.replace("/j/", "/wc/join/").replace("/s/", "/wc/join/")
        try:
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(self.session_dir, headless=False, args=["--use-fake-ui-for-media-stream","--use-fake-device-for-media-stream","--autoplay-policy=no-user-gesture-required","--start-maximized"])
                page = context.pages[0]; Stealth().apply_stealth_sync(page)
                if db_module and meeting_id: db_module.update_bot_status(meeting_id, "FETCHING", "Navigating to Zoom...")
                page.goto(wc_url)
                try:
                    page.wait_for_selector('input[name="input-name"]', timeout=10000)
                    page.fill('input[name="input-name"]', self.bot_name)
                    page.click('button:has-text("Join")')
                except: pass
                time.sleep(10)
                try:
                    audio_btn = page.locator('button:has-text("Join Audio by Computer")')
                    if audio_btn.count() > 0: audio_btn.click()
                except: pass
                if db_module and meeting_id: db_module.update_bot_status(meeting_id, "LIVE", "Renata active in Zoom.")
                if record: self.start_audio_recording(f"Zoom_Meeting_{int(time.time())}")
                if db_module and meeting_id:
                    db_module.set_meeting_bot_status(meeting_id, "CONNECTED", user_email=user_email)
                    db_module.update_meeting_bot_note(meeting_id, "Zoom Recording Active")
                while True:
                    try:
                        if page.is_closed() or page.locator('button:has-text("Leave")').count() == 0: break
                    except: break
                    time.sleep(10)
                if record: self.stop_audio_recording()
                if db_module and meeting_id: db_module.set_meeting_bot_status(meeting_id, "COMPLETED")
        except Exception as e: print(f"Zoom Error: {e}")

    def join_google_meet(self, meet_url, record=True, db_module=None, meeting_id=None, user_email=None):
        if not meeting_id: meeting_id = f"meet_live_{int(time.time())}"
        meet_url = normalize_url(meet_url)
        try:
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(self.session_dir, headless=False, args=["--use-fake-ui-for-media-stream","--use-fake-device-for-media-stream","--autoplay-policy=no-user-gesture-required","--disable-blink-features=AutomationControlled","--start-maximized","--disable-notifications","--no-sandbox","--disable-setuid-sandbox"])
                page = context.pages[0]; Stealth().apply_stealth_sync(page)
                page.goto(meet_url); time.sleep(5)
                try:
                    name_input = page.locator('input[placeholder*="What\'s your name"], input[aria-label*="What\'s your name"]').first
                    if name_input.count() > 0:
                        name_input.fill(self.bot_name); time.sleep(1); page.keyboard.press("Enter"); time.sleep(2)
                        page.evaluate('''() => { const b = Array.from(document.querySelectorAll('button, div[role="button"]')).find(x => x.innerText.includes('Join') || x.innerText.includes('Ask')); if (b) b.click(); }''')
                except: pass
                if "accounts.google.com" in page.url:
                    if db_module and meeting_id: db_module.update_bot_status(meeting_id, "CONNECTING", "Logging in...")
                    if self.automate_google_login(page): page.goto(meet_url); time.sleep(5)
                page.keyboard.press("Control+d"); time.sleep(0.5); page.keyboard.press("Control+e"); time.sleep(1)
                for _ in range(3):
                    btn = page.locator('button:has-text("Join now"), button:has-text("Ask to join"), [aria-label="Join now"], [aria-label="Ask to join"]').first
                    if btn.count() > 0: btn.click(force=True); break
                    time.sleep(2)
                while True:
                    if page.locator('button[aria-label*="Leave call" i]').count() > 0:
                        if db_module and meeting_id: db_module.update_bot_status(meeting_id, "CONNECTED", note="Recording active"); break
                    time.sleep(5)
                if record: self.start_audio_recording(f"Meet_{int(time.time())}")
                alone_since = None
                while True:
                    time.sleep(5)
                    if page.is_closed() or page.locator('text="You left the meeting"').count() > 0: break
                    if page.locator('[data-participant-id]').count() <= 1:
                        if alone_since is None: alone_since = time.time()
                        elif (time.time() - alone_since) > 60: break
                    else: alone_since = None
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
        except Exception as e: print(f"Meet Error: {e}")

def run_auto_pilot(operator_email):
    print(f"+--------------------------------------------------+")
    print(f"| Renata AUTO-PILOT: Concurrent multi-user active  |")
    print(f"| Operator: {operator_email:<38} |")
    print(f"+--------------------------------------------------+")
    session_handled_ids = set()
    while True:
        try:
            # 1. LIVE JOIN INTENTS (ALL USERS)
            pending_joins = db.fetch_all("SELECT * FROM meetings WHERE bot_status = 'JOIN_PENDING' ORDER BY created_at ASC")
            for pending in pending_joins:
                m_id = pending['meeting_id']
                if m_id in session_handled_ids or m_id in _active_jobs: continue
                slot = _acquire_slot()
                if slot is not None:
                    meet_url = pending['meet_url']
                    u_email = pending.get('user_email', operator_email)
                    rec = pending.get('recording_enabled', 1)
                    t = threading.Thread(target=_run_meeting_in_thread, args=(meet_url, m_id, u_email, rec, slot), daemon=True)
                    _active_jobs[m_id] = t
                    t.start()
                    session_handled_ids.add(m_id)

            # 2. CALENDAR SCAN (ALL USERS WITH TOKENS)
            all_users = db.fetch_all("SELECT email FROM users WHERE google_token IS NOT NULL AND google_token != ''")
            now = datetime.now(timezone.utc)
            for user_row in all_users:
                cal_email = user_row['email'] if isinstance(user_row, dict) else user_row[0]
                if gmail_scanner: gmail_scanner.scan_inbox(cal_email)
                service = get_service(cal_email)
                if not service: continue
                events = service.events().list(calendarId='primary', timeMin=now.isoformat().replace('+00:00','Z'), maxResults=5, singleEvents=True, orderBy='startTime').execute().get('items', [])
                for event in events:
                    m_id = event.get('id')
                    if m_id in session_handled_ids or m_id in _active_jobs: continue
                    start_str = event.get('start', {}).get('dateTime', event.get('start', {}).get('date'))
                    s_dt = dt_parser.parse(start_str).replace(tzinfo=timezone.utc) if dt_parser.parse(start_str).tzinfo is None else dt_parser.parse(start_str)
                    diff = (now - s_dt).total_seconds() / 60
                    if -5 <= diff <= 60:
                        url = event.get('hangoutLink')
                        if not url and 'location' in event: url = event['location'] if is_meet_url(event['location']) or is_zoom_url(event['location']) else None
                        if url:
                            slot = _acquire_slot()
                            if slot is not None:
                                db.set_meeting_bot_status(m_id, "JOINING", user_email=cal_email, title=event.get('summary'), start_time=start_str)
                                t = threading.Thread(target=_run_meeting_in_thread, args=(url, m_id, cal_email, 1, slot), daemon=True)
                                _active_jobs[m_id] = t
                                t.start()
                                session_handled_ids.add(m_id)
            time.sleep(30)
        except Exception as e: print(f"Pilot Error: {e}"); time.sleep(60)

def main():
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("command", nargs="?")
    arg_parser.add_argument("--user"); args, unknown = arg_parser.parse_known_args()
    u_email = args.user or (db.fetch_one("SELECT email FROM users LIMIT 1") or {'email':'default@rena.ai'})['email']
    cmd = args.command or (unknown[0] if unknown else "--autopilot")
    if cmd == "--autopilot": run_auto_pilot(u_email)
    elif cmd == "--manual": RenaMeetingBot(user_email=u_email).record_manual_audio()
    else:
        bot = RenaMeetingBot(user_email=u_email)
        if is_meet_url(cmd): bot.join_google_meet(cmd, db_module=db, user_email=u_email)
        elif is_zoom_url(cmd): bot.join_zoom_meeting(cmd, db_module=db, user_email=u_email)

if __name__ == "__main__": main()
