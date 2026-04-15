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
    def __init__(self, bot_name="Renata AI | Meeting Assistant", 
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
                
                if db_module and meeting_id: 
                    db_module.update_bot_status(meeting_id, "LIVE", "Renata active in Zoom. Waiting for admission...")
                
                if record:
                    self._browser_page = page   # give recorder access to the page
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
                        process_meeting_audio(str(self.recording_path), meeting_id, user_email=user_email)
                        db_module.update_bot_status(meeting_id, "COMPLETED", note="Report ready")
                    except Exception as ex:
                        print(f"Zoom Pipeline Fail: {ex}")
                        db_module.update_bot_status(meeting_id, "FAILED", note="Processing error")
        except Exception as e: 
            print(f"Zoom Error: {e}")
            if db_module and meeting_id:
                db_module.update_bot_status(meeting_id, "FAILED", note=f"Zoom error: {str(e)[:100]}")

    def join_google_meet(self, meet_url, record=True, db_module=None, meeting_id=None, user_email=None, guest_mode=False, guest_name="Renata AI | Meeting Assistant"):
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

                # 5. Click Join Button
                try:
                    btn = page.locator('button:has-text("Join now"), button:has-text("Ask to join")').first
                    btn.wait_for(timeout=8000)
                    btn.click(force=True)
                except:
                    print("[Meet Slot {self.slot}] Join button not found")
                
                # 6. Wait for Admission
                while True:
                    if page.locator('button[aria-label*="Leave call" i]').count() > 0:
                        if db_module and meeting_id: 
                            db_module.update_bot_status(meeting_id, "CONNECTED", note=f"Bot joined as {guest_name if guest_mode else PERMANENT_BOT_EMAIL}", user_email=user_email)
                        break
                    
                    if page.locator('text="Waiting to be admitted"').count() > 0:
                        if db_module and meeting_id:
                            db_module.update_bot_status(meeting_id, "IN_LOBBY", note="Waiting for host to admit bot...", user_email=user_email)
                            
                    time.sleep(5)
                
                if record:
                    self._browser_page = page   # give recorder access to the page
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
                        process_meeting_audio(str(self.recording_path), meeting_id, user_email=user_email)
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
                guest_name="Renata AI | Meeting Assistant"
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
    
    while True:
        try:
            session_handled_ids = set()
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
            
            # Persistent trackers for this session
            if not hasattr(run_auto_pilot, "_last_scans"):
                run_auto_pilot._last_scans = {}

            for user_row in all_users:
                cal_email = user_row['email']
                # Respect auto-join setting
                if not user_row.get('bot_auto_join', 1):
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
                
                try:
                    events = service.events().list(
                        calendarId='primary', 
                        timeMin=(now - timedelta(hours=3)).isoformat().replace('+00:00','Z'), 
                        timeMax=(now + timedelta(minutes=5)).isoformat().replace('+00:00','Z'), 
                        maxResults=40, 
                        singleEvents=True, 
                        orderBy='startTime',
                        conferenceDataVersion=1,
                        fields='items(id,summary,start,end,location,hangoutLink,conferenceData),nextPageToken'
                    ).execute().get('items', [])
                    
                    for event in events:
                        m_id = event.get('id')
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
                        
                        start_str = event.get('start', {}).get('dateTime', event.get('start', {}).get('date'))
                        end_str = event.get('end', {}).get('dateTime', event.get('end', {}).get('date'))
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
                            continue

                        # Join meetings that have started already, are still ongoing, or will start within 5 minutes.
                        if parsed_dt <= (now + timedelta(minutes=5)):
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