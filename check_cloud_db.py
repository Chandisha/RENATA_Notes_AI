import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()
url = os.getenv("DATABASE_URL")

try:
    conn = psycopg2.connect(url)
    cur = conn.cursor()
    cur.execute("SELECT pdf_path, transcript_text, transcripts_pdf_path, is_summarized_paid FROM meetings WHERE meeting_id = 'join_1775725444';")
    row = cur.fetchone()
    print(f"Postgres Detail: {row}")
    conn.close()
except Exception as e:
    print(f"Cloud DB Error: {e}")
