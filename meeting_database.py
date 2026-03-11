"""
Meeting Database for Renata Bot
Stores meeting metadata and enables search/history features
Replicates Read.ai's meeting archive and search functionality
"""
import sqlite3
import psycopg2
import psycopg2.extras
import json
import os
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# CRITICAL: Load .env before reading env vars
load_dotenv()

# Database Configuration
DATABASE_URL = os.getenv("DATABASE_URL")  # For PostgreSQL (Vercel/Neon)
DB_PATH = Path("meeting_outputs") / "meetings.db"  # For SQLite (Local)

def get_db_connection():
    """Get a connection to the database (PostgreSQL if URL exists, else SQLite)."""
    if DATABASE_URL:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

def exec_commit(query, params=()):
    """Execute a query and commit."""
    conn = get_db_connection()
    if DATABASE_URL:
        query = query.replace("?", "%s")
        query = query.replace("ON CONFLICT(email) DO UPDATE SET", "ON CONFLICT (email) DO UPDATE SET") 
    
    cursor = conn.cursor()
    cursor.execute(query, params)
    conn.commit()
    last_id = None
    try:
        if not DATABASE_URL:
            last_id = cursor.lastrowid
    except: pass
    conn.close()
    return True, last_id

def fetch_one(query, params=()):
    """Fetch a single result."""
    conn = get_db_connection()
    if DATABASE_URL:
        query = query.replace("?", "%s")
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    else:
        cursor = conn.cursor()
    
    cursor.execute(query, params)
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def fetch_all(query, params=()):
    """Fetch all results."""
    conn = get_db_connection()
    if DATABASE_URL:
        query = query.replace("?", "%s")
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    else:
        cursor = conn.cursor()
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def init_database():
    """Initialize the database with required tables"""
    if not DATABASE_URL:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    pk_def = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
    
    # Create meetings table
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS meetings (
            id {pk_def},
            meeting_id TEXT UNIQUE,
            title TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT,
            duration_minutes INTEGER,
            meet_url TEXT,
            organizer_name TEXT,
            organizer_email TEXT,
            participant_count INTEGER,
            participant_emails TEXT,
            workspace_id TEXT,
            user_email TEXT,
            status TEXT DEFAULT 'completed',
            recording_path TEXT,
            pdf_path TEXT,
            json_path TEXT,
            transcript_text TEXT,
            summary_text TEXT,
            action_items TEXT,
            chapters TEXT,
            sentiment_analysis TEXT,
            engagement_metrics TEXT,
            speaker_analytics TEXT,
            coaching_metrics TEXT,
            is_skipped INTEGER DEFAULT 0,
            bot_status TEXT DEFAULT 'IDLE',
            bot_joined_at TEXT,
            bot_status_note TEXT,
            pdf_blob TEXT,
            is_summarized_paid INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Users Table
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS users (
            email TEXT PRIMARY KEY,
            name TEXT,
            picture TEXT,
            home_address TEXT,
            office_address TEXT,
            theme_mode TEXT DEFAULT 'Light',
            notifications_enabled INTEGER DEFAULT 1,
            audio_output_device TEXT DEFAULT 'Default',
            bot_auto_join INTEGER DEFAULT 1,
            bot_recording_enabled INTEGER DEFAULT 1,
            bot_name TEXT DEFAULT 'Renata AI | Personal Meeting Assistant',
            summary_language TEXT DEFAULT 'English/Hindi',
            google_token TEXT,
            zoom_token TEXT,
            notion_token TEXT,
            notion_db TEXT,
            hubspot_api_key TEXT,
            salesforce_token TEXT,
            subscription_plan TEXT DEFAULT 'Free',
            credits INTEGER DEFAULT 3,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

# --- USER PROFILE OPERATIONS ---
def get_user_profile(email):
    return fetch_one("SELECT * FROM users WHERE email = ?", (email,))

def upsert_user(email, name=None, picture=None):
    if DATABASE_URL:
        query = '''
            INSERT INTO users (email, name, picture)
            VALUES (?, ?, ?)
            ON CONFLICT (email) DO UPDATE SET
                name = COALESCE(users.name, EXCLUDED.name),
                picture = COALESCE(users.picture, EXCLUDED.picture)
        '''
    else:
        query = '''
            INSERT INTO users (email, name, picture)
            VALUES (?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                name = COALESCE(users.name, excluded.name),
                picture = COALESCE(users.picture, excluded.picture)
        '''
    exec_commit(query, (email, name, picture))

# --- MEETING OPERATIONS ---

def add_meeting(meeting_id, title, start_time, **kwargs):
    user_email = kwargs.get('user_email')
    # Convert lists/dicts to JSON strings
    for k, v in kwargs.items():
        if isinstance(v, (list, dict)):
            kwargs[k] = json.dumps(v)
    
    cols = ['meeting_id', 'title', 'start_time'] + list(kwargs.keys())
    vals = [meeting_id, title, start_time] + list(kwargs.values())
    placeholders = ", ".join(["?"] * len(cols))
    
    query = f"INSERT INTO meetings ({', '.join(cols)}) VALUES ({placeholders})"
    
    try:
        success, last_id = exec_commit(query, tuple(vals))
        return success, last_id
    except:
        return update_meeting(meeting_id, kwargs)

def update_meeting(meeting_id, updates):
    set_clauses = []
    values = []
    for key, value in updates.items():
        if value is not None:
            set_clauses.append(f"{key} = ?")
            if isinstance(value, (list, dict)):
                value = json.dumps(value)
            values.append(value)
    
    if not set_clauses: return False, "No updates"
    
    values.append(meeting_id)
    query = f"UPDATE meetings SET {', '.join(set_clauses)}, updated_at = CURRENT_TIMESTAMP WHERE meeting_id = ?"
    success, _ = exec_commit(query, tuple(values))
    return success, success

def set_meeting_bot_status(meeting_id, status, user_email=None, **kwargs):
    updates = {'bot_status': status}
    updates.update(kwargs)
    if user_email: updates['user_email'] = user_email
    
    success, _ = update_meeting(meeting_id, updates)
    if not success:
        # Create minimal record if doesn't exist
        exec_commit("INSERT INTO meetings (meeting_id, title, start_time, bot_status, user_email) VALUES (?, ?, ?, ?, ?)",
                    (meeting_id, kwargs.get('title', 'Upcoming Meeting'), kwargs.get('start_time', datetime.now().isoformat()), status, user_email))
    return True

def update_bot_status(meeting_id, status, note=""):
    return set_meeting_bot_status(meeting_id, status, bot_status_note=note)

def get_active_joining_meeting(user_email):
    """STRICTLY SCOPED: Only get the current user's active meeting."""
    return fetch_one("""
        SELECT meeting_id, bot_status, bot_status_note 
        FROM meetings 
        WHERE user_email = ? AND bot_status IN ('JOIN_PENDING', 'JOINING', 'FETCHING', 'CONNECTING', 'IN_LOBBY', 'LIVE', 'CONNECTED')
        ORDER BY created_at DESC LIMIT 1
    """, (user_email,))

def get_meeting(meeting_id):
    return fetch_one("SELECT * FROM meetings WHERE meeting_id = ?", (meeting_id,))

def get_all_meetings(user_email, limit=50, offset=0, order_by='start_time DESC'):
    """STRICTLY SCOPED: user_email is REQUIRED."""
    if not user_email: return []
    query = f"SELECT * FROM meetings WHERE user_email = ? ORDER BY {order_by} LIMIT ? OFFSET ?"
    return fetch_all(query, (user_email, limit, offset))

def get_meeting_stats(user_email):
    """STRICTLY SCOPED: user_email is REQUIRED. Aggregates data for the specific user."""
    if not user_email: return {}
    
    stats = {}
    params = (user_email.lower(),)
    
    # 1. Core Totals - Use LOWER() for case-insensitive matching
    row = fetch_one("SELECT COUNT(*) as count FROM meetings WHERE LOWER(user_email) = LOWER(?) AND (is_skipped = 0 OR is_skipped IS NULL)", params)
    stats['total_meetings'] = row['count'] if row else 0
    
    # Total Reports (PDFs)
    row = fetch_one("SELECT COUNT(*) as count FROM meetings WHERE LOWER(user_email) = LOWER(?) AND (pdf_path IS NOT NULL OR pdf_blob IS NOT NULL)", params)
    stats['total_reports'] = row['count'] if row else 0
    
    # Duration - if duration is NULL, estimate 30 mins for older sessions to show engagement
    row = fetch_one("SELECT SUM(CASE WHEN duration_minutes IS NULL THEN 30 ELSE duration_minutes END) as sum FROM meetings WHERE LOWER(user_email) = LOWER(?)", params)
    total_minutes = (row['sum'] if row else 0) or 0
    stats['total_duration_hours'] = round(total_minutes / 60, 1)
    
    row = fetch_one("SELECT AVG(participant_count) as avg FROM meetings WHERE LOWER(user_email) = LOWER(?) AND participant_count > 0", params)
    stats['avg_participants'] = round((row['avg'] if row else 0) or 0, 1)

    # 2. Sentiment/Engagement from actual analytics
    eng_rows = fetch_all("SELECT engagement_metrics FROM meetings WHERE LOWER(user_email) = LOWER(?) AND engagement_metrics IS NOT NULL", params)
    total_eng = 0
    total_words = 0
    for row in eng_rows:
        try:
            d = json.loads(row['engagement_metrics'])
            total_eng += d.get('score', 0)
            total_words += d.get('total_words', 0)
        except: continue
    
    stats['avg_engagement_raw'] = round(total_eng / len(eng_rows), 1) if eng_rows else 0
    stats['total_words'] = total_words

    # 3. Dynamic Engagement Score (Growth-based)
    # Give weight to meetings joined, reports produced, and words transcribed
    base_activity = (stats['total_meetings'] * 10) + (stats['total_reports'] * 15)
    word_weight = (total_words // 100)
    final_score = base_activity + word_weight
    stats['engagement_score'] = min(100, max(12 if stats['total_meetings'] > 0 else 0, final_score))

    # App engagement - Platform time
    stats['app_engagement_minutes'] = (total_minutes) + (stats['total_meetings'] * 10) + (stats['total_reports'] * 5)

    # 4. History for Chart (Eng. over time)
    # If no engagement metrics, use a synthetic trend based on reports
    history_rows = fetch_all("""
        SELECT start_time, engagement_metrics, (pdf_path IS NOT NULL) as has_pdf FROM meetings 
        WHERE LOWER(user_email) = LOWER(?)
        ORDER BY start_time ASC LIMIT 10
    """, params)
    
    chart_data = []
    chart_labels = []
    for h in history_rows:
        try:
            score = 0
            if h.get('engagement_metrics'):
                d = json.loads(h['engagement_metrics'])
                score = d.get('score', 0)
            
            # Fallback for reports without explicit metrics yet
            if score == 0 and h.get('has_pdf'):
                score = 65 # Baseline for a completed meeting
            elif score == 0:
                score = 20 # Baseline for a joined but not yet processed meeting
                
            chart_data.append(score)
            dt = datetime.fromisoformat(h['start_time'].replace('Z', '+00:00'))
            chart_labels.append(dt.strftime("%b %d"))
        except: continue
    
    if not chart_data:
        chart_data = [0, 0, 0, 0, 0]
        chart_labels = ["No Data", "No Data", "No Data", "No Data", "No Data"]

    stats['chart_data'] = chart_data
    stats['chart_labels'] = chart_labels

    return stats

def save_meeting_results(meeting_id, transcript, summary, action_items, speaker_stats, engagement, **kwargs):
    updates = {
        'transcript_text': transcript,
        'summary_text': summary,
        'action_items': action_items,
        'speaker_analytics': speaker_stats,
        'engagement_metrics': engagement,
        'status': 'completed'
    }
    updates.update(kwargs)
    return update_meeting(meeting_id, updates)

def get_user_token(email):
    row = fetch_one("SELECT google_token FROM users WHERE email = ?", (email,))
    return row['google_token'] if row else None

# Initialize database on import
init_database()
