import sqlite3
import os
from pathlib import Path

db_path = Path("meeting_outputs") / "meetings.db"
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(meetings)")
    rows = cursor.fetchall()
    for row in rows:
        print(f"Col: {row[1]}, Type: {row[2]}")
    conn.close()
else:
    print(f"DB not found at {db_path}")
