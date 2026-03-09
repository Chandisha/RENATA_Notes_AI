import sqlite3
import os
from pathlib import Path

db_path = Path("meeting_outputs") / "meetings.db"
if db_path.exists():
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("Checking meetings with JOIN_PENDING or active status:")
    rows = cursor.execute("SELECT meeting_id, meet_url, bot_status FROM meetings WHERE bot_status NOT IN ('COMPLETED', 'FAILED', 'IDLE', 'SUPERSEDED')").fetchall()
    for row in rows:
        print(f"ID: {row['meeting_id']} | URL: {row['meet_url']} | Status: {row['bot_status']}")
    
    conn.close()
else:
    print("Local SQLite not found.")
