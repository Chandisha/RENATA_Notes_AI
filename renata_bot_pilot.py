import os
import sys
import time
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
def is_meet_url(text: str) -> bool:
    if not isinstance(text, str):
        return False
    return bool(re.search(r"meet\.google\.com", text)) or "google.com/meet" in text

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
PERMANENT_BOT_EMAIL = os.getenv("BOT_EMAIL", "renata@nexren.ai")
PERMANENT_BOT_PASS = os.getenv("BOT_PASSWORD", "")
BOT_SESSION_DIR = os.path.join(os.getcwd(), "bot_session", "main")
os.makedirs(BOT_SESSION_DIR, exist_ok=True)

if not PERMANENT_BOT_PASS:
    print("⚠ WARNING: BOT_PASSWORD not set in .env! Google login will fail.")
    print("  Add to .env:  BOT_EMAIL=renata@nexren.ai")
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
        print(f"[Pilot] No token found for {user_email} — user must log in again")
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
        elif creds and creds.expired and not creds.refresh_token:
            print(f"[Pilot] Token EXPIRED and no refresh_token for {user_email} — user must log in again")
            return None
        return build('calendar', 'v3', credentials=creds)
    except Exception as e:
        print(f"[Pilot] Token error for {user_email}: {e}")
        return None

# --- RTCPeerConnection Hook — Injected BEFORE page load ---
# Maintains a global registry of all peer connections so we can
# enumerate their audio receivers when recording starts.
RTC_AUDIO_HOOK = """
(function() {
    console.log('[Renata] Injecting RTC Hook...');
    window.__renataActivePCs = window.__renataActivePCs || [];
    try {
        const OrigRTC = window.RTCPeerConnection;
        window.RTCPeerConnection = function(...args) {
            const pc = new OrigRTC(...args);
            window.__renataActivePCs.push(pc);
            console.log('[Renata] RTCPeerConnection created. Total:', window.__renataActivePCs.length);
            pc.addEventListener('connectionstatechange', () => {
                if (pc.connectionState === 'closed') {
                    window.__renataActivePCs = window.__renataActivePCs.filter(p => p !== pc);
                }
            });
            return pc;
        };
        Object.setPrototypeOf(window.RTCPeerConnection, OrigRTC);
        Object.defineProperty(window.RTCPeerConnection, 'prototype', { value: OrigRTC.prototype });
        console.log('[Renata] Hook Ready — PC registry enabled.');
    } catch(e) { console.error('[Renata] Hook Fail:', e); }
})();
"""

# --- MAIN BOT CLASS ---
class RenaMeetingBot:
    def __init__(self, bot_name="Meet AI | Meeting Assistant", 
                 audio_device="audio=CABLE Output (VB-Audio Virtual Cable)", 
                 user_email=None, session_dir=None, guest_mode=False):
        self.user_email = user_email
        self.guest_mode = guest_mode  # MULTI-USER FIX: If True, join as guest instead of bot account
        if user_email:
            try:
                profile = db.get_user_profile(user_email)
                if profile and profile.get('bot_name'):
                    bot_name = profile['bot_name']
            except Exception: 
                pass
            
        self.bot_name = bot_name
        self.audio_device = audio_device  # kept for legacy fallback only
        self.output_dir = Path("meeting_outputs") / "recordings"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.audio_process = None        # legacy ffmpeg process (unused in browser mode)
        self.recording_path = None
        self.session_dir = session_dir if session_dir else BOT_SESSION_DIR
        self.slot = 0 # Default to slot 0
        # --- Browser-native recording state ---
        self._browser_page = None        # active Playwright page
        self._audio_chunks = []          # raw webm chunks received from browser
        self._recording_active = False

    def set_slot(self, slot):
        self.slot = slot

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
        """Session-first login: If this is a multi-user (guest_mode), skip login. Otherwise use bot credentials."""
        try:
            # MULTI-USER FIX: If guest_mode is enabled, don't login - Google Meet will prompt for name
            if hasattr(self, 'guest_mode') and self.guest_mode:
                print(f"[Login] ✓ Guest mode enabled for {self.user_email} - skipping Google login")
                return True

            if not PERMANENT_BOT_EMAIL or not PERMANENT_BOT_PASS:
                print("[Login] ERROR: BOT_EMAIL or BOT_PASSWORD not set in .env!")
                print("[Login] Falling back to guest mode...")
                return True  # Allow guest mode to proceed

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



    # -------------------------------------------------------------------------
    # BROWSER-NATIVE AUDIO RECORDING (No VB-Cable / ffmpeg needed)
    # Uses the browser's built-in MediaRecorder API via Playwright.
    # Each browser context is fully isolated — unlimited concurrent bots.
    # -------------------------------------------------------------------------
    # BROWSER-NATIVE AUDIO RECORDING — ALL SLOTS
    # Uses the RTCPeerConnection hook injected via page.add_init_script() BEFORE
    # the page loads. This guarantees ALL incoming WebRTC audio tracks are captured
    # from the very first packet, with zero VB-Cable / FFmpeg dependency.
    # Works for unlimited parallel meetings — each browser context is fully isolated.
    # -------------------------------------------------------------------------

    def start_audio_recording(self, filename):
        """
        Start browser-native audio capture for ALL slots.

        The RTC_AUDIO_HOOK was pre-injected via add_init_script() before navigation,
        so window.__renataDest already contains a MediaStreamDestination that is
        receiving all remote audio tracks via the patched RTCPeerConnection.

        We just need to attach a MediaRecorder to that stream and start collecting chunks.
        No VB-Cable, no FFmpeg, no virtual audio devices needed at all.
        """
        self._audio_chunks = []
        self._recording_active = True

        if not self._browser_page:
            print(f"[Audio Slot {self.slot}] ERROR: No browser page — cannot record.")
            return

        self.recording_path = self.output_dir / f"{filename}.webm"
        page = self._browser_page

        # Expose Python callback so JS can stream raw audio chunks back
        try:
            page.expose_function("_renataAudioChunk", self._on_audio_chunk)
        except Exception:
            pass  # Already registered (safe to ignore)

        print(f"[Audio Slot {self.slot}] Attaching MediaRecorder — scanning all live RTC receivers...")
        page.evaluate("""
        () => {
            if (window._renataRecorder && window._renataRecorder.state !== 'inactive') {
                console.log('[Renata] Recorder already running.');
                return;
            }

            // Fresh AudioContext + destination to mix all remote tracks
            window.__renataAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
            window.__renataDest = window.__renataAudioCtx.createMediaStreamDestination();

            let tracksConnected = 0;

            // METHOD 1: Enumerate receivers from all open RTCPeerConnections
            const pcs = window.__renataActivePCs || [];
            console.log('[Renata] Open PeerConnections found:', pcs.length);
            pcs.forEach(pc => {
                if (pc.connectionState === 'closed' || pc.connectionState === 'failed') return;
                pc.getReceivers().forEach(receiver => {
                    const track = receiver.track;
                    if (track && track.kind === 'audio' && track.readyState === 'live') {
                        try {
                            const src = window.__renataAudioCtx.createMediaStreamSource(new MediaStream([track]));
                            src.connect(window.__renataDest);
                            tracksConnected++;
                            console.log('[Renata] Connected receiver track from PC registry');
                        } catch(e) { console.warn('[Renata] Track connect error:', e); }
                    }
                });
            });

            // METHOD 2: Fallback — scan all <audio>/<video> srcObjects
            if (tracksConnected === 0) {
                console.warn('[Renata] No PeerConnection receivers found. Trying DOM elements...');
                document.querySelectorAll('audio, video').forEach(el => {
                    if (el.srcObject) {
                        el.srcObject.getAudioTracks().forEach(track => {
                            try {
                                const src = window.__renataAudioCtx.createMediaStreamSource(new MediaStream([track]));
                                src.connect(window.__renataDest);
                                tracksConnected++;
                                console.log('[Renata] Connected DOM audio track');
                            } catch(e) {}
                        });
                    }
                });
            }

            console.log('[Renata] Total audio tracks connected:', tracksConnected);

            // Resume AudioContext if blocked by autoplay policy
            if (window.__renataAudioCtx.state === 'suspended') {
                window.__renataAudioCtx.resume();
            }

            // Pick best supported mimeType
            const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
                ? 'audio/webm;codecs=opus' : 'audio/webm';

            const recorder = new MediaRecorder(window.__renataDest.stream, { mimeType });
            window._renataRecorder = recorder;

            recorder.ondataavailable = async (e) => {
                if (e.data && e.data.size > 0) {
                    const buf = await e.data.arrayBuffer();
                    window._renataAudioChunk(Array.from(new Uint8Array(buf)));
                }
            };

            recorder.onerror = (e) => console.error('[Renata] Recorder error:', e.error);
            recorder.start(3000);
            console.log('[Renata] MediaRecorder started. mimeType:', mimeType);
        }
        """)
        print(f"[Audio Slot {self.slot}] Recording started → {self.recording_path.name}")

    def _on_audio_chunk(self, chunk_array):
        """Callback — receives raw audio bytes from browser MediaRecorder."""
        if self._recording_active:
            self._audio_chunks.append(bytes(chunk_array))

    def stop_audio_recording(self):
        """Stop browser-native recording and save the captured .webm file."""
        if not self._recording_active:
            return

        self._recording_active = False
        print(f"[Audio Slot {self.slot}] Stopping recording...")

        # Stop the in-browser MediaRecorder and close the AudioContext
        if self._browser_page:
            try:
                self._browser_page.evaluate("""
                () => {
                    if (window._renataRecorder && window._renataRecorder.state !== 'inactive') {
                        window._renataRecorder.stop();
                        window._renataRecorder = null;
                        console.log('[Renata] MediaRecorder stopped.');
                    }
                    if (window.__renataAudioCtx && window.__renataAudioCtx.state !== 'closed') {
                        window.__renataAudioCtx.close();
                    }
                }
                """)
            except Exception:
                pass  # Page may already be closed — that's fine

        # Wait for the final ondataavailable chunk to arrive
        time.sleep(2)

        # Save all collected chunks to disk (ALL slots use browser-native now)
        if self._audio_chunks and self.recording_path:
            try:
                with open(self.recording_path, 'wb') as f:
                    for chunk in self._audio_chunks:
                        f.write(chunk)
                print(f"[Audio Slot {self.slot}] Saved → {self.recording_path}")
            except Exception as e:
                print(f"[Audio Slot {self.slot}] Error saving audio: {e}")
        elif not self._audio_chunks:
            print(f"[Audio Slot {self.slot}] WARNING: No audio chunks received — recording may be silent or empty.")

        # Integrity check
        if self.recording_path and self.recording_path.exists():
            size = self.recording_path.stat().st_size
            if size < 5000:
                print(f"[Audio Slot {self.slot}] ⚠ File very small ({size} bytes) — audio capture may have failed.")
                print(f"[Audio Slot {self.slot}]   Tip: Check that the RTC hook was injected before page load.")
            else:
                print(f"[Audio Slot {self.slot}] ✓ Recording finalized: {self.recording_path.name} ({size:,} bytes)")
        else:
            print(f"[Audio Slot {self.slot}] ⚠ Recording file not found at: {self.recording_path}")

    def record_manual_audio(self):
        """Legacy manual recording stub."""
        print("[Audio] Manual recording requires a live browser session.")

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
                
                # 3. Wait for Admission (Check for Leave and Participants buttons)
                was_admitted = False
                admission_deadline = time.time() + 900 # 15 min wait
                while time.time() < admission_deadline:
                    # Zoom Web Client admission indicators
                    has_leave_btn = page.locator('button:has-text("Leave")').is_visible()
                    has_participants_btn = page.locator('button:has-text("Participants"), button[aria-label="Participants"]').is_visible()
                    
                    if has_leave_btn and has_participants_btn:
                        was_admitted = True
                        print(f"[Zoom Slot {self.slot}] HOST ADMITTED THE BOT ✓ — starting recording now.")
                        break
                    time.sleep(5)

                if record and was_admitted:
                    self._browser_page = page   # give recorder access to the page
                    self.start_audio_recording(f"Zoom_Meeting_{int(time.time())}")
                    
                if db_module and meeting_id:
                    if was_admitted:
                        db_module.set_meeting_bot_status(meeting_id, "CONNECTED", user_email=user_email, bot_status_note="Bot admitted! Capturing meeting intelligence...")
                    else:
                        db_module.update_bot_status(meeting_id, "COMPLETED", note="Host did not admit bot. No recording made.", user_email=user_email)
                        return # Exit early, no recording

                # Monitor Loop — wait for meeting to end or everyone leaves
                alone_since = None
                ALONE_TIMEOUT_SECS = 15
                ever_active = False 
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
                                print("[Zoom Bot] Leave button gone. Will exit in 15s if not restored...")
                            elif (time.time() - alone_since) > ALONE_TIMEOUT_SECS:
                                break
                        else:
                            # Track participation - if we ever saw others, it was a real meeting
                            # Zoom web client doesn't easily expose participant count without opening sidebar, 
                            # but seeing the Leave button implies we are admitted.
                            ever_active = True 
                            alone_since = None
                    except Exception:
                        break
                    time.sleep(10)
                
                if record: 
                    self.stop_audio_recording()
                
                if db_module and meeting_id:
                    # ONLY use Gemini if meeting was active and file has data
                    rec_size = self.recording_path.stat().st_size if self.recording_path and self.recording_path.exists() else 0
                    if ever_active and rec_size > 5000:
                        db_module.update_bot_status(meeting_id, "PROCESSING", note="Meeting ended - Processing...")
                        try:
                            from meeting_notes_generator import process_meeting_audio
                            process_meeting_audio(str(self.recording_path), meeting_id, user_email=user_email)
                            db_module.update_bot_status(meeting_id, "COMPLETED", note="Report ready")
                        except Exception as ex:
                            print(f"Zoom Pipeline Fail: {ex}")
                            db_module.update_bot_status(meeting_id, "FAILED", note="Processing error")
                    else:
                        print(f"[Zoom Bot] Skipping Gemini API (Active: {ever_active}, Size: {rec_size} bytes)")
                        db_module.update_bot_status(meeting_id, "COMPLETED", note="Meeting empty - No intelligence needed.", user_email=user_email)
                        db_module.exec_commit("UPDATE meetings SET status='completed' WHERE meeting_id=?", (meeting_id,))
        except Exception as e: 
            print(f"Zoom Error: {e}")
            if db_module and meeting_id:
                db_module.update_bot_status(meeting_id, "FAILED", note=f"Zoom error: {str(e)[:100]}")

    def join_google_meet(self, meet_url, record=True, db_module=None, meeting_id=None, user_email=None, guest_mode=False, guest_name="Renata AI | Meeting Assistant", scheduled_start=None):
        if not meeting_id: 
            meeting_id = f"meet_live_{int(time.time())}"
        
        meet_url = normalize_url(meet_url)
        print(f"[Meet Slot {self.slot}] Mode: {'GUEST (' + guest_name + ')' if guest_mode else 'AUTHENTICATED'}")
        
        try:
            with sync_playwright() as p:
                # Use HEADLESS=FALSE for slot 0 (Authenticated) to avoid Google blocks
                # Guest slots (1+) can stay headless as they are less restricted
                is_headless = guest_mode
                
                context = p.chromium.launch_persistent_context(
                    self.session_dir, 
                    headless=is_headless, 
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
                
                # 1. Inject RTC Audio Hook BEFORE navigation
                page.add_init_script(RTC_AUDIO_HOOK)

                # 2. Authentication or Guest Mode
                if guest_mode:
                    print(f"[Meet Slot {self.slot}] Navigation to: {meet_url} (GUEST)")
                    page.goto(meet_url, timeout=60000)
                else:
                    # Slot 0: Ensure logged in first
                    if not self.automate_google_login(page):
                        print("Warning: Google Login check finished with some issues.")
                    
                    print(f"[Meet Slot {self.slot}] Navigation to: {meet_url} (AUTH)")
                    page.goto(meet_url, timeout=60000)
                
                print(f"[Meet Slot {self.slot}] Page loaded. Stabilizing...")
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=20000)
                except Exception:
                    print(f"[Meet Slot {self.slot}] Stabilization wait timed out, proceeding anyway...")
                time.sleep(2)
                
                if not guest_mode and "accounts.google.com" in page.url:
                    if db_module and meeting_id: 
                        db_module.update_bot_status(meeting_id, "CONNECTING", "Re-authenticating...")
                    self.automate_google_login(page)
                    page.goto(meet_url)
                    time.sleep(5)

                if db_module and meeting_id: 
                    db_module.update_bot_status(meeting_id, "CONNECTING", "Entering lobby...", user_email=user_email)
                
                # 3. Mute mic/camera
                try:
                    page.keyboard.press("Control+d")
                    time.sleep(0.5)
                    page.keyboard.press("Control+e")
                    time.sleep(1)
                except: pass

                # 4. Handle Guest Name Input
                if guest_mode:
                    try:
                        name_input = page.locator('input[placeholder*="name" i], input[aria-label*="name" i]').first
                        if name_input.is_visible(timeout=5000):
                            name_input.fill(guest_name)
                            print(f"[Meet Slot {self.slot}] Entered guest name: {guest_name}")
                            time.sleep(1)
                    except:
                        print(f"[Meet Slot {self.slot}] Name input not found — likely already in lobby.")

                # 5. Click Join Button - retry until it appears or until the meeting is joined
                joined = False
                join_deadline = time.time() + 600
                while not joined and time.time() < join_deadline:
                    try:
                        btn = page.locator('button:has-text("Join now"), button:has-text("Ask to join")').first
                        if btn.count() > 0:
                            btn.click(force=True)
                            joined = True
                            break
                    except Exception:
                        pass

                    if page.locator('button[aria-label*="Leave call" i]').count() > 0 or page.locator('text="Waiting to be admitted"').count() > 0:
                        joined = True
                        break

                    print(f"[Meet Slot {self.slot}] Join button not found, retrying in 5s...")
                    time.sleep(5)

                if not joined:
                    print(f"[Meet Slot {self.slot}] Join button not found after 5 minutes. Continuing to wait for admission if available.")

                # 6. Wait for Admission with Patient Lobby Logic
                # The bot will ONLY start recording AFTER the host admits it.
                # USER REQUEST: Wait for 15 minutes after the scheduled start time before giving up.
                admission_deadline = time.time() + 900  # Fallback 15 mins
                if scheduled_start:
                    try:
                        dt_start = dt_parser.parse(scheduled_start)
                        if dt_start.tzinfo is None: dt_start = dt_start.replace(tzinfo=timezone.utc)
                        # Admission deadline is Start Time + 15 Minutes
                        planned_deadline = (dt_start + timedelta(minutes=15)).timestamp()
                        admission_deadline = max(admission_deadline, planned_deadline)
                        print(f"[Meet Slot {self.slot}] Patient Lobby: Will wait until {datetime.fromtimestamp(admission_deadline).strftime('%H:%M:%S')} for admission (15m buffer).")
                    except: pass

                # CRITICAL: Track actual admission — do NOT record in lobby
                was_admitted = False
                while True:
                    # Bot is inside the meeting (Leave call button visible AND Meeting details button shown) = admitted
                    # This dual-check prevents false positives from lobby UI
                    has_leave_btn = page.locator('button[aria-label*="Leave call" i]').is_visible()
                    has_details_btn = page.locator('button[aria-label*="Meeting details" i], button[aria-label*="Chat with everyone" i]').is_visible()

                    if has_leave_btn and has_details_btn:
                        was_admitted = True
                        if db_module and meeting_id:
                            db_module.update_bot_status(meeting_id, "CONNECTED",
                                note=f"Bot admitted and joined as {guest_name if guest_mode else PERMANENT_BOT_EMAIL}",
                                user_email=user_email)
                        print(f"[Meet Slot {self.slot}] HOST ADMITTED THE BOT ✓ — starting recording now.")
                        break

                    if time.time() > admission_deadline:
                        print(f"[Meet Slot {self.slot}] Admission timeout — host did not admit. Leaving lobby without recording.")
                        if db_module and meeting_id:
                            db_module.update_bot_status(meeting_id, "COMPLETED",
                                note="Host did not admit bot in time. No recording made.",
                                user_email=user_email)
                            db_module.exec_commit("UPDATE meetings SET status='completed' WHERE meeting_id=?", (meeting_id,))
                        break  # was_admitted stays False

                    if page.locator('text="Waiting to be admitted"').count() > 0 or page.locator('text="Asking to join"').count() > 0:
                        if db_module and meeting_id:
                            db_module.update_bot_status(meeting_id, "IN_LOBBY",
                                note="In lobby — waiting for host to admit. NOT recording.",
                                user_email=user_email)

                    time.sleep(5)

                # ONLY start recording if host actually admitted the bot
                if record and was_admitted:
                    self._browser_page = page   # give recorder access to the page
                    self.start_audio_recording(f"Meet_{int(time.time())}")
                elif not was_admitted:
                    print(f"[Meet Slot {self.slot}] Bot was never admitted — skipping recording entirely.")
                    return  # Exit cleanly — no processing needed
                    
                # Monitor Loop — wait for meeting to end
                alone_since = None
                ALONE_TIMEOUT_SECS = 15  # USER REQUEST: Leave 15 seconds after everyone else leaves
                CHECK_INTERVAL = 10
                ever_active = False # USER REQUEST: Track if the meeting actually started (host joined)

                while True:
                    page.wait_for_timeout(CHECK_INTERVAL * 1000)
                    try:
                        if page.is_closed():
                            break
                        if page.locator('text="You left the meeting"').count() > 0:
                            break
                        
                        # --- Check for user cancellation or exit ---

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
                                if cnt > 1: # Bot + at least 1 other
                                    ever_active = True 
                                break

                        # Bot itself counts as 1 — if only 1 (or 0) left, start timer
                        if participant_count <= 1:
                            # STRATEGIC PATIENCE logic:
                            # 1. If meeting NEVER started (no host/guest ever joined), wait 15m.
                            # 2. If meeting DID start (ever_active is True) and now empty, leave in 30s.
                            is_grace_period = False
                            
                            # Grace period ONLY if meeting never actually had anyone else
                            if not ever_active and scheduled_start:
                                try:
                                    dt_start = dt_parser.parse(scheduled_start)
                                    if dt_start.tzinfo is None: dt_start = dt_start.replace(tzinfo=timezone.utc)
                                    # USER REQUEST: Shorten grace period for empty rooms to avoid recording 15m silence
                                    grace_deadline = (dt_start + timedelta(minutes=5)).timestamp()
                                    if time.time() < grace_deadline:
                                        is_grace_period = True
                                        if alone_since is None: # Only log once
                                            print(f"[Bot] Room is empty (Never Started). Waiting up to 5m past start...")
                                except: pass

                            if is_grace_period:
                                alone_since = None # Reset timer while in grace period
                            elif alone_since is None:
                                alone_since = time.time()
                                print(f"[Bot] Only bot remains in meeting. Will leave in {ALONE_TIMEOUT_SECS}s...")
                                if db_module and meeting_id:
                                    db_module.update_bot_status(meeting_id, "CONNECTED",
                                        note=f"No participants detected. Leaving in {ALONE_TIMEOUT_SECS}s...",
                                        user_email=user_email)
                            elif (time.time() - alone_since) > ALONE_TIMEOUT_SECS:
                                print("[Bot] Timeout reached (Bot remains alone). Auto-leaving meeting.")
                                
                                # If we are leaving because we were alone, and we already tried joining once,
                                # mark COMPLETED so we don't spam join attempts on an empty meeting.
                                if db_module and meeting_id:
                                    db_module.update_bot_status(meeting_id, "COMPLETED", 
                                        note="Bot left: No participants detected after window.", 
                                        user_email=user_email)
                                    db_module.exec_commit("UPDATE meetings SET status='completed' WHERE meeting_id=?", (meeting_id,))

                                # Click Leave call button
                                try:
                                    leave_btn = page.locator('button[aria-label*="Leave call" i]').first
                                    if leave_btn.count() > 0:
                                        leave_btn.click()
                                        time.sleep(2)
                                except Exception: pass
                                break
                        else:
                            if alone_since is not None:
                                print("[Bot] Participants joined! Resetting alone timer.")
                            alone_since = None
                    except Exception:
                        break
                
                self.stop_audio_recording()
                
                if db_module and meeting_id:
                    # ONLY use Gemini if meeting was active and file has data
                    rec_size = self.recording_path.stat().st_size if self.recording_path and self.recording_path.exists() else 0
                    if ever_active and rec_size > 5000:
                        db_module.update_bot_status(meeting_id, "PROCESSING", note="Meeting ended - Processing...")
                        try:
                            from meeting_notes_generator import process_meeting_audio
                            process_meeting_audio(str(self.recording_path), meeting_id, user_email=user_email)
                            # Mark COMPLETED so report shows in dashboard Reports section
                            db_module.update_bot_status(meeting_id, "COMPLETED", note="Report ready. Check Reports section.", user_email=user_email)
                            db_module.exec_commit("UPDATE meetings SET status='completed' WHERE meeting_id=? AND user_email=?", (meeting_id, user_email))
                            print(f"[Bot] Pipeline done for {meeting_id} → {user_email}. Report ready.")
                        except Exception as ex:
                            print(f"Pipeline Fail: {ex}")
                            db_module.update_bot_status(meeting_id, "FAILED", note="Processing error")
                    else:
                        print(f"[Bot] Skipping Gemini API (Active: {ever_active}, Size: {rec_size} bytes)")
                        db_module.update_bot_status(meeting_id, "COMPLETED", note="Meeting empty - No intelligence needed.", user_email=user_email)
                        db_module.exec_commit("UPDATE meetings SET status='completed' WHERE meeting_id=? AND user_email=?", (meeting_id, user_email))
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
    Maps concurrency slots to isolated virtual audio devices.
    Supports two drivers — switch via AUDIO_DRIVER in .env:

      AUDIO_DRIVER=vbcable  (default, uses VB-Audio Virtual Cable)
      AUDIO_DRIVER=sar      (uses Synchronous Audio Router — free & open source)

    VB-Cable Mapping (default):
      Slot 0 -> Standard VB-Cable (Free)
      Slot 1 -> VB-Cable A        (Donation required)
      Slot 2 -> VB-Cable B        (Donation required)
      Slot 3 -> VB-Cable C        (Donation required)
      Slot 4 -> VB-Cable D        (Donation required)

    SAR Mapping (100% Free, Open Source):
      Slot 0 -> SAR Slot 0
      Slot 1 -> SAR Slot 1
      Slot 2 -> SAR Slot 2
      Slot 3 -> SAR Slot 3
      Slot 4 -> SAR Slot 4
      (Create these endpoint names in SAR Settings GUI)
    """
    driver = os.getenv("AUDIO_DRIVER", "vbcable").lower().strip()

    if driver == "sar":
        # Synchronous Audio Router — free, open source
        # Endpoint names must match what you created in SAR Settings
        mapping = {
            0: "audio=SAR Slot 0",
            1: "audio=SAR Slot 1",
            2: "audio=SAR Slot 2",
            3: "audio=SAR Slot 3",
            4: "audio=SAR Slot 4",
        }
    else:
        # VB-Audio Virtual Cable (default)
        mapping = {
            0: "audio=CABLE Output (VB-Audio Virtual Cable)",
            1: "audio=CABLE-A Output (VB-Audio Cable A)",
            2: "audio=CABLE-B Output (VB-Audio Cable B)",
            3: "audio=CABLE-C Output (VB-Audio Cable C)",
            4: "audio=CABLE-D Output (VB-Audio Cable D)",
        }

    device = mapping.get(slot, mapping[0])
    print(f"[Audio] Slot {slot} -> {device} (driver: {driver})")
    return device

def _run_meeting_in_thread(meet_url, meeting_id, user_email, record, slot, start_time=None):
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
        
        # MULTI-USER FIX: Use guest mode for slot > 0 (multi-user scenarios)
        is_guest_mode = (slot > 0)
        thread_bot = RenaMeetingBot(user_email=user_email, session_dir=session_dir, audio_device=audio_dev, guest_mode=is_guest_mode)
        thread_bot.set_slot(slot)
        
        if is_meet_url(meet_url):
            thread_bot.join_google_meet(
                meet_url, 
                record=record, 
                db_module=db, 
                meeting_id=meeting_id, 
                user_email=user_email,
                guest_mode=is_guest_mode,
                guest_name="Renata AI | Meeting Assistant",
                scheduled_start=start_time
            )
        elif is_zoom_url(meet_url):
            thread_bot.join_zoom_meeting(meet_url, record=record, db_module=db, meeting_id=meeting_id, user_email=user_email)
        else:
            thread_bot.join_google_meet(
                meet_url, 
                record=record, 
                db_module=db, 
                meeting_id=meeting_id, 
                user_email=user_email,
                guest_mode=is_guest_mode,
                guest_name="Renata AI | Meeting Assistant"
            )
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
    session_handled_ids = set() # MOVED OUTSIDE: Persistent trackers for this session
    
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
                        
                        # IGNORE STALE REQUESTS: Skip if older than 10 mins OR created before this bot instance started
                        if age_mins > 10 or c_dt < (PILOT_BOOT_TIME - timedelta(seconds=10)): 
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
            all_users = db.fetch_all("SELECT email, bot_auto_join, bot_recording_enabled FROM users WHERE google_token IS NOT NULL OR zoom_token IS NOT NULL")
            now = datetime.now(timezone.utc)
            
            # Persistent trackers for this session
            if not hasattr(run_auto_pilot, "_last_scans"):
                run_auto_pilot._last_scans = {}

            for user_row in all_users:
                cal_email = user_row['email']
                # Respect auto-join setting
                if not user_row.get('bot_auto_join', 1):
                    # print(f"[Pilot] SKIP {cal_email} — auto-join disabled in settings")
                    continue
                
                # OPTIMIZATION: Only scan Gmail every 60 seconds (prevents throttling & lag)
                if gmail_scanner:
                    last_scan = run_auto_pilot._last_scans.get(cal_email, 0)
                    if (time.time() - last_scan) > 60:
                        try:
                            print(f"[Pilot] Scanning Gmail for {cal_email}...")
                            gmail_scanner.scan_inbox(cal_email)
                            run_auto_pilot._last_scans[cal_email] = time.time()
                        except Exception as ge: 
                            print(f"Gmail Error: {ge}")
                
                service = get_service(cal_email)
                if not service: 
                    continue
                
                print(f"[Pilot] Checking calendar for {cal_email}...")
                
                try:
                    events = service.events().list(
                        calendarId='primary', 
                        # NARROW WINDOW: Only look from NOW forward (0 min lookback) to avoid any previous meetings
                        timeMin=now.isoformat().replace('+00:00','Z'), 
                        timeMax=(now + timedelta(minutes=45)).isoformat().replace('+00:00','Z'), 
                        maxResults=40, 
                        singleEvents=True, 
                        orderBy='startTime',
                        fields='items(id,summary,start,end,location,hangoutLink,conferenceData),nextPageToken'
                    ).execute().get('items', [])
                    
                    print(f"[Pilot] {cal_email}: {len(events)} event(s) in window")
                    for event in events:
                        m_id = event.get('id')
                        title = event.get('summary', 'Untitled')
                        url = event.get('hangoutLink')
                        if not url:
                            conf = event.get('conferenceData', {})
                            if conf:
                                for entry in conf.get('entryPoints', []):
                                    uri = entry.get('uri')
                                    if uri and (is_meet_url(uri) or is_zoom_url(uri)):
                                        url = uri
                                        break
                        if not url and 'location' in event: 
                            loc = event['location']
                            url = loc if is_meet_url(loc) or is_zoom_url(loc) else None
                        
                        norm_url = normalize_url(url) if url else None
                        
                        if (m_id, cal_email) in session_handled_ids or (norm_url, cal_email) in session_handled_ids or (m_id, cal_email) in _active_jobs: 
                            continue
                        
                        start_str = event.get('start', {}).get('dateTime')
                        end_str = event.get('end', {}).get('dateTime')
                        if not start_str:
                            continue
                        
                        parsed_dt = dt_parser.parse(start_str)
                        if parsed_dt.tzinfo is None:
                            parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
                        parsed_end = None
                        if end_str:
                            parsed_end = dt_parser.parse(end_str)
                            if parsed_end.tzinfo is None:
                                parsed_end = parsed_end.replace(tzinfo=timezone.utc)

                        # Skip events that have already ended
                        if parsed_end and now > parsed_end:
                            print(f"[Pilot] SKIP '{title}' — already ended")
                            continue

                        # STRICT UPCOMING FILTER: Skip if meeting started more than 10 minutes ago
                        # This prevents the bot from joining "old" or "stale" meetings that are nearing completion.
                        if parsed_dt < (now - timedelta(minutes=10)):
                            print(f"[Pilot] SKIP '{title}' — started too long ago (>{(now-parsed_dt).total_seconds()/60:.1f}m ago)")
                            session_handled_ids.add((m_id, cal_email))
                            continue

                        # USER REQUEST: Wait for the meeting to start. Only join if it starts within next 60 seconds
                        # (Previously joined 30m early — now joins at most 1m early)
                        if parsed_dt > now + timedelta(minutes=1):
                            continue

                        print(f"[Pilot] CANDIDATE '{title}' for {cal_email} — url={'YES' if url else 'NO'}")

                        # Skip meetings already completed/failed for this user.
                        # Check both bot_status (TRANSITORY) and status (PERSISTENT).
                        db_meeting = db.fetch_one("SELECT bot_status, status, is_skipped FROM meetings WHERE meeting_id = ? AND user_email = ?", (m_id, cal_email))
                        if db_meeting:
                            if db_meeting.get('is_skipped', 0):
                                if (m_id, cal_email) not in session_handled_ids:
                                    print(f"[Pilot] SKIP '{title}' — marked skipped by user")
                                    session_handled_ids.add((m_id, cal_email))
                                continue
                            
                            current_bot_status = (db_meeting.get('bot_status') or '').upper()
                            current_status = (db_meeting.get('status') or '').upper()

                            if current_bot_status in ('COMPLETED', 'FAILED') or current_status == 'COMPLETED':
                                print(f"[Pilot] SKIP '{title}' — already processed (Status: {current_status})")
                                session_handled_ids.add((m_id, cal_email))
                                continue

                        if not url:
                            print(f"[Pilot] SKIP '{title}' — NO meet/zoom link found in event")
                            session_handled_ids.add((m_id, cal_email))
                            continue
                        url = normalize_url(url)

                        # FINAL: Also check by URL in the DB — prevents re-joining same
                        # link that was completed under a different event ID
                        url_db = db.fetch_one(
                            "SELECT bot_status, status FROM meetings WHERE meet_url = ? AND user_email = ?",
                            (url, cal_email)
                        )
                        if url_db:
                            url_bot_s = (url_db.get('bot_status') or '').upper()
                            url_status = (url_db.get('status') or '').upper()
                            if url_bot_s in ('COMPLETED', 'FAILED') or url_status == 'COMPLETED':
                                print(f"[Pilot] SKIP '{title}' — URL already recorded & completed")
                                session_handled_ids.add((m_id, cal_email))
                                session_handled_ids.add((url, cal_email))
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
                            
                            db.set_meeting_bot_status(m_id, "DISPATCHING", user_email=cal_email, title=event.get('summary'), start_time=start_str, meet_url=url, bot_status_note=f"Scheduled event detected. Assigning Slot {slot}...")
                            
                            # Respect user's global recording preference
                            rec_enabled = user_row.get('bot_recording_enabled', 1)
                            
                            t = threading.Thread(
                                target=_run_meeting_in_thread, 
                                args=(url, m_id, cal_email, rec_enabled, slot, start_str), 
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