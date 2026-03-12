import sqlite3
import os
from pathlib import Path

db_path = Path("meeting_outputs") / "meetings.db"
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Check tables again
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    print(f"Tables found: {tables}")

    if 'meetings' in tables:
        print("\n--- Users in meetings table ---")
        rows = cursor.execute("SELECT DISTINCT user_email FROM meetings").fetchall()
        for r in rows:
            print(f"Email: {r['user_email']}")
        
        print("\n--- Meeting counts ---")
        rows = cursor.execute("SELECT user_email, COUNT(*) as count FROM meetings GROUP BY user_email").fetchall()
        for r in rows:
            print(f"User: {r['user_email']}, Count: {r['count']}")
    
    conn.close()
else:
    print(f"DB not found at {db_path}")
