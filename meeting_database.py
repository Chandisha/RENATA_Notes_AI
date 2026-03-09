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

# CRITICAL: Load .env before reading env vars - must happen before any os.getenv() calls
load_dotenv()

# Database Configuration
DATABASE_URL = os.getenv("DATABASE_URL")  # For PostgreSQL (Vercel/Neon)
DB_PATH = Path("meeting_outputs") / "meetings.db"  # For SQLite (Local)

def get_db_connection():
    """Get a connection to the database (PostgreSQL if URL exists, else SQLite)."""
    if DATABASE_URL:
        # PostgreSQL Connection
        print(">>> DB: CONNECTING TO POSTGRESQL")
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    else:
        # SQLite Connection
        print(f">>> DB: CONNECTING TO SQLITE ({DB_PATH})")
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

def get_cursor(conn):
    """Helper to get a dictionary-ready cursor."""
    if DATABASE_URL:
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    else:
        return conn.cursor()

def exec_commit(query, params=()):
    """Execute a query and commit."""
    conn = get_db_connection()
    # Replace ? with %s if PostgreSQL
    if DATABASE_URL:
        query = query.replace("?", "%s")
        # Handle specific dialect differences if needed
        query = query.replace("ON CONFLICT(email) DO UPDATE SET", "ON CONFLICT (email) DO UPDATE SET") 
    
    cursor = conn.cursor()
    cursor.execute(query, params)
    conn.commit()
    last_id = None
    try:
        if DATABASE_URL:
            # PostgreSQL doesn't have lastrowid on the cursor in the same way
            # We would need RETURNING id if we wanted it
            pass
        else:
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
        # Ensure directory exists for SQLite
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Use TEXT instead of INTEGER PRIMARY KEY AUTOINCREMENT for PG compatibility if needed
    # Actually, serial is better for PG. We'll stick to basic DDL and let PG handle it or provide a separate schema.
    
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
    
    # Check for pdf_blob column (migration)
    try:
        cursor.execute("ALTER TABLE meetings ADD COLUMN IF NOT EXISTS pdf_blob TEXT")
    except: pass

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
    
    # Workspace Tables
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS workspaces (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            owner_email TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS workspace_members (
            id {pk_def},
            workspace_id TEXT REFERENCES workspaces(id),
            user_email TEXT NOT NULL,
            role TEXT DEFAULT 'member',
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(workspace_id, user_email)
        )
    ''')

    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS workspace_chats (
            id {pk_def},
            workspace_id TEXT REFERENCES workspaces(id),
            sender_email TEXT NOT NULL,
            sender_name TEXT,
            message TEXT,
            attachment_path TEXT,
            attachment_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()

# --- USER PROFILE OPERATIONS ---
def get_user_profile(email):
    """Retrieve user profile from database"""
    return fetch_one("SELECT * FROM users WHERE email = ?", (email,))

def update_user_profile(email, updates):
    """Update user profile fields"""
    set_clauses = []
    values = []
    for key, val in updates.items():
        if key != 'email':
            set_clauses.append(f"{key} = ?")
            values.append(val)
    
    if not set_clauses: return False
    
    values.append(email)
    query = f"UPDATE users SET {', '.join(set_clauses)}, updated_at = CURRENT_TIMESTAMP WHERE email = ?"
    exec_commit(query, tuple(values))
    return True

def upsert_user(email, name=None, picture=None):
    """Create or update basic user info from login"""
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

def add_meeting(
    meeting_id, title, start_time, end_time=None, duration_minutes=None,
    meet_url=None, organizer_name=None, organizer_email=None, participant_count=0,
    participant_emails=None, recording_path=None, pdf_path=None, json_path=None,
    transcript_text=None, summary_text=None, action_items=None, chapters=None,
    sentiment_analysis=None, engagement_metrics=None, speaker_analytics=None,
    coaching_metrics=None, user_email=None
):
    """Add a new meeting to the database"""
    # Convert lists/dicts to JSON strings
    participant_emails_json = json.dumps(participant_emails) if participant_emails else None
    action_items_json = json.dumps(action_items) if action_items else None
    chapters_json = json.dumps(chapters) if chapters else None
    sentiment_json = json.dumps(sentiment_analysis) if sentiment_analysis else None
    engagement_json = json.dumps(engagement_metrics) if engagement_metrics else None
    speaker_json = json.dumps(speaker_analytics) if speaker_analytics else None
    coaching_json = json.dumps(coaching_metrics) if coaching_metrics else None
    
    query = '''
        INSERT INTO meetings (
            meeting_id, title, start_time, end_time, duration_minutes,
            meet_url, organizer_name, organizer_email, participant_count,
            participant_emails, user_email, recording_path, pdf_path, json_path,
            transcript_text, summary_text, action_items, chapters,
            sentiment_analysis, engagement_metrics, speaker_analytics, coaching_metrics
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    '''
    params = (
        meeting_id, title, start_time, end_time, duration_minutes,
        meet_url, organizer_name, organizer_email, participant_count,
        participant_emails_json, user_email, recording_path, pdf_path, json_path,
        transcript_text, summary_text, action_items_json, chapters_json,
        sentiment_json, engagement_json, speaker_json, coaching_json
    )
    
    try:
        success, last_id = exec_commit(query, params)
        return success, last_id
    except:
        # Fallback to update if exists
        return update_meeting(meeting_id, {
            'title': title, 'start_time': start_time, 'end_time': end_time,
            'duration_minutes': duration_minutes, 'meet_url': meet_url,
            'organizer_name': organizer_name, 'organizer_email': organizer_email,
            'participant_count': participant_count, 'participant_emails': participant_emails,
            'recording_path': recording_path, 'pdf_path': pdf_path, 'json_path': json_path,
            'transcript_text': transcript_text, 'summary_text': summary_text, 'action_items': action_items,
            'chapters': chapters, 'sentiment_analysis': sentiment_analysis,
            'engagement_metrics': engagement_metrics, 'speaker_analytics': speaker_analytics,
            'coaching_metrics': coaching_metrics
        })

def update_meeting(meeting_id, updates):
    """Update an existing meeting"""
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

def toggle_meeting_skip(meeting_id, skip_status: bool, title="Unknown Meeting", start_time=None):
    status = 1 if skip_status else 0
    success, _ = update_meeting(meeting_id, {'is_skipped': status})
    if not success:
        exec_commit("INSERT INTO meetings (meeting_id, title, start_time, is_skipped) VALUES (?, ?, ?, ?)",
                    (meeting_id, title, start_time, status))
    return True

def set_meeting_bot_status(meeting_id, status, user_email=None, joined_at=None, status_note=None, title="Upcoming Meeting", start_time=None):
    updates = {'bot_status': status}
    if joined_at: updates['bot_joined_at'] = joined_at
    if status_note: updates['bot_status_note'] = status_note
    if user_email: updates['user_email'] = user_email
    
    success, _ = update_meeting(meeting_id, updates)
    if not success:
        exec_commit("INSERT INTO meetings (meeting_id, title, start_time, bot_status, user_email) VALUES (?, ?, ?, ?, ?)",
                    (meeting_id, title, start_time or datetime.now().isoformat(), status, user_email))
    return True

def update_meeting_bot_note(meeting_id, note):
    update_meeting(meeting_id, {'bot_status_note': note})
    return True

def update_bot_status(meeting_id, status, note=""):
    """Thin wrapper for Pilot compatibility"""
    return set_meeting_bot_status(meeting_id, status, status_note=note)

def get_active_joining_meeting(user_email=None):
    if user_email:
        return fetch_one("""
            SELECT meeting_id, bot_status, bot_status_note 
            FROM meetings 
            WHERE user_email = ? AND bot_status IN ('JOIN_PENDING', 'JOINING', 'FETCHING', 'CONNECTING', 'IN_LOBBY', 'LIVE', 'CONNECTED')
            ORDER BY created_at DESC LIMIT 1
        """, (user_email,))
    return fetch_one("""
        SELECT meeting_id, bot_status, bot_status_note 
        FROM meetings 
        WHERE bot_status IN ('JOIN_PENDING', 'JOINING', 'FETCHING', 'CONNECTING', 'IN_LOBBY', 'LIVE', 'CONNECTED')
        ORDER BY created_at DESC LIMIT 1
    """)

def delete_user_account(email):
    """Delete all user data - meetings, tokens, profile."""
    exec_commit("DELETE FROM meetings WHERE user_email = ?", (email,))
    exec_commit("DELETE FROM workspace_members WHERE user_email = ?", (email,))
    exec_commit("DELETE FROM users WHERE email = ?", (email,))
    return True

def get_user_profile(email):
    """Get user profile data."""
    return fetch_one("SELECT * FROM users WHERE email = ?", (email,))

def update_user_profile(email, settings):
    """Update user profile fields dynamically."""
    if not settings: return
    set_parts = ", ".join([f"{k} = ?" for k in settings.keys()])
    values = list(settings.values()) + [email]
    exec_commit(f"UPDATE users SET {set_parts}, updated_at = CURRENT_TIMESTAMP WHERE email = ?", tuple(values))

def get_meeting(meeting_id):
    """Get a specific meeting by ID"""
    return fetch_one("SELECT * FROM meetings WHERE meeting_id = ?", (meeting_id,))

def get_all_meetings(user_email=None, limit=50, offset=0, order_by='start_time DESC'):
    """Get all meetings with pagination, scoped by user_email if provided."""
    if user_email:
        query = f"SELECT * FROM meetings WHERE user_email = ? ORDER BY {order_by} LIMIT ? OFFSET ?"
        return fetch_all(query, (user_email, limit, offset))
    else:
        query = f"SELECT * FROM meetings ORDER BY {order_by} LIMIT ? OFFSET ?"
        return fetch_all(query, (limit, offset))

def search_meetings(query, user_email=None, limit=20):
    """
    Search meetings by title or transcript content
    
    Args:
        query: Search term
        limit: Maximum results to return
    
    Returns:
        List of matching meetings
    """
    init_database()
    
    search_pattern = f"%{query}%"
    
    if user_email:
        query_sql = '''
            SELECT * FROM meetings 
            WHERE user_email = ? 
              AND (title LIKE ? OR transcript_text LIKE ? OR summary_text LIKE ?)
            ORDER BY start_time DESC
            LIMIT ?
        '''
        return fetch_all(query_sql, (user_email, search_pattern, search_pattern, search_pattern, limit))
    else:
        query_sql = '''
            SELECT * FROM meetings 
            WHERE title LIKE ? OR transcript_text LIKE ? OR summary_text LIKE ?
            ORDER BY start_time DESC
            LIMIT ?
        '''
        return fetch_all(query_sql, (search_pattern, search_pattern, search_pattern, limit))
    
    return [dict(row) for row in rows]

def get_meeting_stats(user_email=None):
    """Get aggregated meeting stats, scoped by user_email if provided."""
    init_database()
    
    stats = {}
    
    # Base query filter
    where_clause = "WHERE user_email = ?" if user_email else "WHERE 1=1"
    params = (user_email,) if user_email else ()
    
    # Total meetings
    row = fetch_one(f"SELECT COUNT(*) as count FROM meetings {where_clause}", params)
    stats['total_meetings'] = row['count'] if row else 0
    
    # Total duration
    row = fetch_one(f"SELECT SUM(duration_minutes) as sum FROM meetings {where_clause} AND duration_minutes IS NOT NULL", params)
    total_minutes = (row['sum'] if row else 0) or 0
    stats['total_duration_hours'] = round(total_minutes / 60, 1)
    
    # Average participants
    row = fetch_one(f"SELECT AVG(participant_count) as avg FROM meetings {where_clause} AND participant_count > 0", params)
    stats['avg_participants'] = round((row['avg'] if row else 0) or 0, 1)
    
    # Meetings this week
    if DATABASE_URL:
        # PostgreSQL syntax
        week_query = f"{where_clause} AND start_time >= (CURRENT_TIMESTAMP - INTERVAL '7 days')::text"
    else:
        # SQLite syntax
        week_query = f"{where_clause} AND start_time >= date('now', '-7 days')"
        
    row = fetch_one(f"SELECT COUNT(*) as count FROM meetings {week_query}", params)
    stats['meetings_this_week'] = row['count'] if row else 0

    # Aggregated Metrics (Engagement & Words)
    eng_rows = fetch_all("SELECT engagement_metrics FROM meetings WHERE engagement_metrics IS NOT NULL")
    total_eng = 0
    total_words = 0
    for row in eng_rows:
        try:
            d = json.loads(row['engagement_metrics'])
            total_eng += d.get('score', 0)
            total_words += d.get('total_words', 0)
        except: continue
    
    stats['avg_engagement'] = round(total_eng / len(eng_rows), 1) if eng_rows else 0
    stats['total_words'] = total_words

    # Storage Usage
    def get_dir_size(path='.'):
        total = 0
        with os.scandir(path) as it:
            for entry in it:
                if entry.is_file():
                    total += entry.stat().size
                elif entry.is_dir():
                    total += get_dir_size(entry.path)
        return total

    try:
        size_bytes = get_dir_size(str(DB_PATH.parent))
        if size_bytes < 1024 * 1024:
            stats['storage_used'] = f"{round(size_bytes / 1024, 1)} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            stats['storage_used'] = f"{round(size_bytes / (1024*1024), 1)} MB"
        else:
            stats['storage_used'] = f"{round(size_bytes / (1024*1024*1024), 1)} GB"
    except:
        stats['storage_used'] = "0 MB"

    # Speaker Talk Time (Last 10 Meetings) - Aggregated
    rows = fetch_all('''
        SELECT speaker_analytics FROM meetings 
        WHERE speaker_analytics IS NOT NULL 
        ORDER BY start_time DESC 
        LIMIT 10
    ''')
    speaker_totals = {}
    for row in rows:
        try:
            data = json.loads(row['speaker_analytics'])
            for spk, vals in data.items():
                if spk not in speaker_totals:
                    speaker_totals[spk] = 0
                speaker_totals[spk] += vals.get('percentage', 0)
        except: continue
    
    # Average the percentages
    if rows:
        agg_speakers = {k: round(v / len(rows), 1) for k, v in speaker_totals.items()}
        # Ensure we have common names if mapping exists
        stats['speaker_distribution'] = agg_speakers
    else:
        stats['speaker_distribution'] = {}
    
    return stats

def save_meeting_results(meeting_id, transcript, summary, action_items, speaker_stats, engagement, pdf_path=None, json_path=None, pdf_blob=None):
    """Save final AI intelligence and analytics to the DB (Includes Cloud Sync for PDF)"""
    updates = {
        'transcript_text': transcript,
        'summary_text': summary,
        'action_items': action_items,
        'speaker_analytics': speaker_stats,
        'engagement_metrics': engagement,
        'pdf_path': pdf_path,
        'json_path': json_path,
        'pdf_blob': pdf_blob,
        'status': 'completed'
    }
    return update_meeting(meeting_id, updates)

# --- WORKSPACE OPERATIONS (Restored & Enhanced) ---

    workspace_id = ""
    # Ensure uniqueness
    for _ in range(10):
        import secrets
        workspace_id = secrets.token_hex(4).upper() # 8 characters
        if not fetch_one("SELECT id FROM workspaces WHERE id = ?", (workspace_id,)):
            break
            
    try:
        exec_commit(
            "INSERT INTO workspaces (id, name, owner_email, description) VALUES (?, ?, ?, ?)",
            (workspace_id, name, owner_email, description)
        )
        # Add owner as first member
        exec_commit(
            "INSERT INTO workspace_members (workspace_id, user_email, role) VALUES (?, ?, 'owner')",
            (workspace_id, owner_email)
        )
        return True, workspace_id
    except Exception as e:
        return False, str(e)

def join_workspace(workspace_id, email):
    """Join an existing workspace using its unique ID"""
    workspace_id = workspace_id.strip().upper()
    try:
        # Verify workspace exists
        if not fetch_one("SELECT id FROM workspaces WHERE id = ?", (workspace_id,)):
            return False, "Workspace not found. Check the ID."
            
        exec_commit(
            "INSERT INTO workspace_members (workspace_id, user_email, role) VALUES (?, ?, 'member')",
            (workspace_id, email)
        )
        return True, "Joined successfully!"
    except Exception as e:
        if "UNIQUE" in str(e).upper():
            return False, "You are already a member of this workspace."
        return False, str(e)

def get_user_workspaces(email):
    """Get all workspaces a user belongs to"""
    return fetch_all('''
        SELECT w.*, wm.role 
        FROM workspaces w
        JOIN workspace_members wm ON w.id = wm.workspace_id
        WHERE wm.user_email = ?
    ''', (email,))

def get_workspace_members(workspace_id):
    """List all members of a workspace"""
    return fetch_all("SELECT user_email, role, joined_at FROM workspace_members WHERE workspace_id = ?", (workspace_id,))

def send_workspace_message(workspace_id, sender_email, sender_name, message, attachment_path=None, attachment_name=None):
    """Send a message to workspace chat"""
    try:
        exec_commit('''
            INSERT INTO workspace_chats 
            (workspace_id, sender_email, sender_name, message, attachment_path, attachment_name)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (workspace_id, sender_email, sender_name, message, attachment_path, attachment_name))
        return True
    except:
        return False

def get_workspace_messages(workspace_id, limit=50):
    """Get recent messages from workspace chat"""
    return fetch_all('''
        SELECT * FROM workspace_chats 
        WHERE workspace_id = ? 
        ORDER BY created_at ASC 
        LIMIT ?
    ''', (workspace_id, limit))

# --- ASSISTANT CHAT HISTORY OPERATIONS ---

def create_assistant_thread(user_email, title="New Conversation"):
    """Create a new personal chat thread for the assistant"""
    import secrets
    thread_id = secrets.token_hex(8).upper()
    try:
        exec_commit(
            "INSERT INTO assistant_threads (id, user_email, title) VALUES (?, ?, ?)",
            (thread_id, user_email, title)
        )
        return thread_id
    except:
        return None

def save_assistant_message(thread_id, role, content):
    """Save a single message to a chat thread"""
    try:
        exec_commit(
            "INSERT INTO assistant_messages (thread_id, role, content) VALUES (?, ?, ?)",
            (thread_id, role, content)
        )
        return True
    except:
        return False

def get_user_assistant_threads(user_email):
    """Get all chat threads for a specific user"""
    return fetch_all("SELECT * FROM assistant_threads WHERE user_email = ? ORDER BY created_at DESC", (user_email,))

def get_assistant_thread_messages(thread_id):
    """Get all messages for a specific chat thread"""
    return fetch_all("SELECT role, content FROM assistant_messages WHERE thread_id = ? ORDER BY created_at ASC", (thread_id,))

def update_assistant_thread_title(thread_id, new_title):
    """Update conversation title (first few words of first user message)"""
    try:
        exec_commit("UPDATE assistant_threads SET title = ? WHERE id = ?", (new_title, thread_id))
        return True
    except:
        return False

def get_user_token(email):
    """Retrieve the serialized Google OAuth token for a user."""
    row = fetch_one("SELECT google_token FROM users WHERE email = ?", (email,))
    return row['google_token'] if row else None

def get_all_folders():
    """Returns list of folders - placeholder for now"""
    return []

# Initialize database on import
init_database()

# Example usage
if __name__ == "__main__":
    # Test database
    print("Testing Meeting Database...")
    
    # Add a test meeting
    success, meeting_id = add_meeting(
        meeting_id="test_123",
        title="Test Meeting",
        start_time="2026-02-08T14:00:00Z",
        end_time="2026-02-08T15:00:00Z",
        duration_minutes=60,
        meet_url="https://meet.google.com/test",
        organizer_name="John Doe",
        organizer_email="john@example.com",
        participant_count=5,
        participant_emails=["john@example.com", "jane@example.com"],
        summary_text="Discussed project timeline and deliverables",
        action_items=["Review proposal", "Schedule follow-up"]
    )
    
    print(f"Added meeting: {success}, ID: {meeting_id}")
    
    # Get stats
    stats = get_meeting_stats()
    print(f"\nStats: {stats}")
    
    # Search
    results = search_meetings("project")
    print(f"\nSearch results: {len(results)} meetings found")
