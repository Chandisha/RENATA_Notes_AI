import meeting_database as db
from datetime import datetime

print(">>> Checking Database for active/pending meetings...")
try:
    rows = db.fetch_all("SELECT meeting_id, meet_url, bot_status, created_at FROM meetings WHERE bot_status NOT IN ('COMPLETED', 'FAILED', 'IDLE', 'SUPERSEDED')")
    if not rows:
        print("No active/pending meetings found.")
    for row in rows:
        print(f"ID: {row.get('meeting_id')} | URL: {row.get('meet_url')} | Status: {row.get('bot_status')} | Created: {row.get('created_at')}")
    
    # Optional: Clear them to stop the loop
    # db.exec_commit("UPDATE meetings SET bot_status = 'SUPERSEDED', bot_status_note = 'Cleaned up by system' WHERE bot_status = 'JOIN_PENDING'")
    # print("Updated all JOIN_PENDING to SUPERSEDED.")
except Exception as e:
    print(f"Error checking DB: {e}")
