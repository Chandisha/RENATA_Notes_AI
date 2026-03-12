import sqlite3
import os
from pathlib import Path

db_path = Path("meeting_outputs") / "meetings.db"
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    rows = cursor.execute("SELECT meeting_id, pdf_path, pdf_blob FROM meetings").fetchall()
    for r in rows:
        print(f"ID: {r['meeting_id']}, PDF: {r['pdf_path']}, Blob: {r['pdf_blob']}")
    
    conn.close()
else:
    print(f"DB not found at {db_path}")
