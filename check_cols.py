import sqlite3
import os
from pathlib import Path

db_path = Path("meeting_outputs") / "meetings.db"
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(meetings)")
    rows = cursor.fetchall()
    cols = [r[1] for r in rows]
    print(f"Columns: {cols}")
    conn.close()
else:
    print(f"DB not found at {db_path}")
