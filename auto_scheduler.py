"""
Auto-Join Scheduler for Renata Bot
Monitors calendar and automatically joins meetings based on user preferences
This replicates Read.ai's automatic meeting join feature
"""
import os
import sys
import time
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

import config
from renata_bot_pilot import get_upcoming_events

# Track which meetings we've already joined
joined_meetings = set()

def should_join_meeting(event, auto_join_delay):
    """
    Determine if bot should join this meeting now
    Returns: (should_join: bool, reason: str)
    """
    meeting_id = event['id']
    
    # Check if already joined
    if meeting_id in joined_meetings:
        return False, "Already joined"
    
    # Check if meeting has a Google Meet link
    meet_url = event.get('hangoutLink', '')
    if not meet_url:
        return False, "No Meet link"
    
    # Get meeting start time
    start = event['start'].get('dateTime', event['start'].get('date'))
    if not start:
        return False, "No start time"
    
    # Calculate time difference
    now = datetime.now(timezone.utc)
    start_time = datetime.fromisoformat(start.replace('Z', '+00:00'))
    
    # Time since meeting started (in seconds)
    time_diff = (now - start_time).total_seconds()
    
    # Join if meeting started between 0 and (delay + 60) seconds ago
    # This gives a 60-second window after the delay
    if 0 <= time_diff <= (auto_join_delay + 60):
        return True, f"Meeting started {int(time_diff)}s ago"
    
    return False, f"Not time yet (starts in {-int(time_diff)}s)" if time_diff < 0 else "Too late to join"

def join_meeting(event):
    """Launch bot to join the meeting"""
    meet_url = event.get('hangoutLink', '')
    summary = event.get('summary', 'Meeting')
    meeting_id = event['id']
    
    print(f"🚀 Auto-joining: {summary}")
    print(f"   URL: {meet_url}")
    
    # Launch the bot in a new process
    try:
        subprocess.Popen(
            [sys.executable, "renata_bot_pilot.py", meet_url],
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
        )
        joined_meetings.add(meeting_id)
        print(f"✅ Bot launched successfully for: {summary}")
        return True
    except Exception as e:
        print(f"❌ Failed to launch bot: {e}")
        return False

def monitor_calendar():
    """Main monitoring loop"""
    print("=" * 60)
    print("🤖 Renata Auto-Join Scheduler Started")
    print("=" * 60)
    
    # Load config
    cfg = config.load_config()
    auto_join_enabled = cfg.get('auto_join_enabled', False)
    auto_join_delay = cfg.get('auto_join_delay_seconds', 30)
    
    if not auto_join_enabled:
        print("⚠️  Auto-join is DISABLED in config")
        print("   Enable it in the frontend settings to start auto-joining")
        return
    
    print(f"✅ Auto-join ENABLED")
    print(f"⏱️  Join delay: {auto_join_delay} seconds after meeting starts")
    print(f"🔄 Checking calendar every 30 seconds...")
    print()
    
    check_count = 0
    
    while True:
        try:
            # Reload config each iteration in case user changed settings
            cfg = config.load_config()
            auto_join_enabled = cfg.get('auto_join_enabled', False)
            
            if not auto_join_enabled:
                print("⚠️  Auto-join disabled. Stopping scheduler...")
                break
            
            auto_join_delay = cfg.get('auto_join_delay_seconds', 30)
            
            check_count += 1
            current_time = datetime.now().strftime("%I:%M:%S %p")
            print(f"[{current_time}] Check #{check_count}: Fetching upcoming meetings...")
            
            # Get upcoming events (look back 5 minutes to catch recent starts)
            events = get_upcoming_events(max_results=10)
            
            if not events:
                print("   No meetings found")
            else:
                print(f"   Found {len(events)} meeting(s)")
                
                for event in events:
                    summary = event.get('summary', 'Untitled Meeting')
                    should_join, reason = should_join_meeting(event, auto_join_delay)
                    
                    if should_join:
                        print(f"\n   ✨ JOINING: {summary} ({reason})")
                        join_meeting(event)
                        print()
                    else:
                        # Only print if it's a future meeting (to reduce noise)
                        if "Not time yet" in reason:
                            print(f"   ⏳ {summary}: {reason}")
            
            print()
            
            # Wait 30 seconds before next check
            time.sleep(30)
            
        except KeyboardInterrupt:
            print("\n\n🛑 Scheduler stopped by user")
            break
        except Exception as e:
            print(f"❌ Error in monitoring loop: {e}")
            print("   Retrying in 30 seconds...")
            time.sleep(30)

if __name__ == "__main__":
    # Check if token exists
    if not os.path.exists('token.json'):
        print("❌ Error: token.json not found")
        print("   Please run the frontend and authorize with Google Calendar first")
        sys.exit(1)
    
    monitor_calendar()
