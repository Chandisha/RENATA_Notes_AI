import os
import psycopg2
from dotenv import load_dotenv
import meeting_database as db

load_dotenv()

def migrate():
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        print("Error: DATABASE_URL not found in environment.")
        return

    print(f"Connecting to PostgreSQL at {DATABASE_URL.split('@')[-1]}...")
    try:
        db.init_database()
        print("✅ Database initialized successfully on PostgreSQL.")
    except Exception as e:
        print(f"❌ Migration failed: {e}")

if __name__ == "__main__":
    migrate()
