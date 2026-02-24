"""
Meeting Database for Renata Bot
Stores meeting metadata and enables search/history features
Replicates Read.ai's meeting archive and search functionality
"""
import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path("meeting_outputs") / "meetings.db"

def get_db_connection():
    """Get a connection to the database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    """Initialize the database with required tables"""
    # Ensure directory exists
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create meetings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS meetings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            is_skipped INTEGER DEFAULT 0, -- 1 if user cancelled bot for this meeting
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Workspace Tables (Robust Re-creation to fix datatype mismatch)
    try:
        # Check if workspaces table has TEXT id
        cursor.execute("PRAGMA table_info(workspaces)")
        columns = cursor.fetchall()
        if columns and columns[0][2].upper() != 'TEXT':
            # Mismatch detected, recreate tables
            cursor.execute("DROP TABLE IF EXISTS workspace_chats")
            cursor.execute("DROP TABLE IF EXISTS workspace_members")
            cursor.execute("DROP TABLE IF EXISTS workspaces")
    except:
        pass

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS workspaces (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            owner_email TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS workspace_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id TEXT,
            user_email TEXT NOT NULL,
            role TEXT DEFAULT 'member',
            joined_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
            UNIQUE(workspace_id, user_email)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS workspace_chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id TEXT,
            sender_email TEXT NOT NULL,
            sender_name TEXT,
            message TEXT,
            attachment_path TEXT,
            attachment_name TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS assistant_threads (
            id TEXT PRIMARY KEY,
            user_email TEXT NOT NULL,
            title TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS assistant_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id TEXT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (thread_id) REFERENCES assistant_threads(id)
        )
    ''')

    # Create users table for profile settings
    cursor.execute('''
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
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Gmail Intelligence Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS gmail_intelligence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT,
            message_id TEXT UNIQUE,
            category TEXT, -- 'deadline', 'project', 'action_item'
            subject TEXT,
            snippet TEXT,
            date_mentioned TEXT,
            is_dismissed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # --- MIGRATIONS ---
    def add_column_if_missing(table, column, type_def):
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {type_def}")
        except sqlite3.OperationalError:
            pass # Column likely already exists

    add_column_if_missing("meetings", "bot_status", "TEXT DEFAULT 'IDLE'")
    add_column_if_missing("meetings", "bot_joined_at", "TEXT")
    add_column_if_missing("meetings", "bot_status_note", "TEXT")

    add_column_if_missing("meetings", "chapters", "TEXT")
    add_column_if_missing("meetings", "sentiment_analysis", "TEXT")
    add_column_if_missing("meetings", "engagement_metrics", "TEXT")
    add_column_if_missing("meetings", "speaker_analytics", "TEXT")
    add_column_if_missing("meetings", "coaching_metrics", "TEXT")
    add_column_if_missing("meetings", "workspace_id", "INTEGER")
    
    # User migrations
    add_column_if_missing("users", "theme_mode", "TEXT DEFAULT 'Light'")
    add_column_if_missing("users", "subscription_plan", "TEXT DEFAULT 'Free'")
    add_column_if_missing("users", "credits", "INTEGER DEFAULT 3")
    add_column_if_missing("meetings", "is_summarized_paid", "INTEGER DEFAULT 0")
    add_column_if_missing("meetings", "is_skipped", "INTEGER DEFAULT 0")
    add_column_if_missing("users", "notifications_enabled", "INTEGER DEFAULT 1")
    add_column_if_missing("users", "audio_output_device", "TEXT DEFAULT 'Default'")
    add_column_if_missing("users", "bot_auto_join", "INTEGER DEFAULT 1")
    add_column_if_missing("users", "bot_recording_enabled", "INTEGER DEFAULT 1")
    add_column_if_missing("users", "bot_name", "TEXT DEFAULT 'Rena AI | Meeting Assistant'")
    add_column_if_missing("users", "summary_language", "TEXT DEFAULT 'English/Hindi'")
    add_column_if_missing("users", "notion_token", "TEXT")
    add_column_if_missing("users", "notion_db", "TEXT")
    add_column_if_missing("users", "hubspot_api_key", "TEXT")
    add_column_if_missing("users", "salesforce_token", "TEXT")

    # Create index for faster searches
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_start_time ON meetings(start_time)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_title ON meetings(title)
    ''')
    
    conn.commit()
    conn.close()

# --- USER PROFILE OPERATIONS ---
def get_user_profile(email):
    """Retrieve user profile from database"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def update_user_profile(email, updates):
    """Update user profile fields"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    set_clauses = []
    values = []
    for key, val in updates.items():
        if key != 'email': # Email is immutable
            set_clauses.append(f"{key} = ?")
            values.append(val)
    
    if not set_clauses:
        conn.close()
        return False
        
    set_clauses.append("updated_at = CURRENT_TIMESTAMP")
    values.append(email)
    
    cursor.execute(f"UPDATE users SET {', '.join(set_clauses)} WHERE email = ?", values)
    conn.commit()
    conn.close()
    return True

def upsert_user(email, name=None, picture=None):
    """Create or update basic user info from login"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO users (email, name, picture)
        VALUES (?, ?, ?)
        ON CONFLICT(email) DO UPDATE SET
            name = COALESCE(users.name, excluded.name),
            picture = COALESCE(users.picture, excluded.picture)
    ''', (email, name, picture))
    conn.commit()
    conn.close()
# --- MEETING OPERATIONS ---

def add_meeting(
    meeting_id,
    title,
    start_time,
    end_time=None,
    duration_minutes=None,
    meet_url=None,
    organizer_name=None,
    organizer_email=None,
    participant_count=0,
    participant_emails=None,
    recording_path=None,
    pdf_path=None,
    json_path=None,
    transcript_text=None,
    summary_text=None,
    action_items=None,
    chapters=None,
    sentiment_analysis=None,
    engagement_metrics=None,
    speaker_analytics=None,
    coaching_metrics=None
):
    """Add a new meeting to the database"""
    init_database()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Convert lists/dicts to JSON strings
    participant_emails_json = json.dumps(participant_emails) if participant_emails else None
    action_items_json = json.dumps(action_items) if action_items else None
    chapters_json = json.dumps(chapters) if chapters else None
    sentiment_json = json.dumps(sentiment_analysis) if sentiment_analysis else None
    engagement_json = json.dumps(engagement_metrics) if engagement_metrics else None
    speaker_json = json.dumps(speaker_analytics) if speaker_analytics else None
    coaching_json = json.dumps(coaching_metrics) if coaching_metrics else None
    
    try:
        cursor.execute('''
            INSERT INTO meetings (
                meeting_id, title, start_time, end_time, duration_minutes,
                meet_url, organizer_name, organizer_email, participant_count,
                participant_emails, recording_path, pdf_path, json_path,
                transcript_text, summary_text, action_items, chapters,
                sentiment_analysis, engagement_metrics, speaker_analytics, coaching_metrics
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            meeting_id, title, start_time, end_time, duration_minutes,
            meet_url, organizer_name, organizer_email, participant_count,
            participant_emails_json, recording_path, pdf_path, json_path,
            transcript_text, summary_text, action_items_json, chapters_json,
            sentiment_json, engagement_json, speaker_json, coaching_json
        ))
        
        conn.commit()
        meeting_db_id = cursor.lastrowid
        conn.close()
        return True, meeting_db_id
        
    except sqlite3.IntegrityError:
        # Meeting already exists, update it instead
        conn.close()
        return update_meeting(meeting_id, {
            'title': title,
            'start_time': start_time,
            'end_time': end_time,
            'duration_minutes': duration_minutes,
            'meet_url': meet_url,
            'organizer_name': organizer_name,
            'organizer_email': organizer_email,
            'participant_count': participant_count,
            'participant_emails': participant_emails,
            'recording_path': recording_path,
            'pdf_path': pdf_path,
            'json_path': json_path,
            'transcript_text': transcript_text,
            'summary_text': summary_text,
            'action_items': action_items,
            'chapters': chapters,
            'sentiment_analysis': sentiment_analysis,
            'engagement_metrics': engagement_metrics,
            'speaker_analytics': speaker_analytics,
            'coaching_metrics': coaching_metrics
        })

def update_meeting(meeting_id, updates):
    """Update an existing meeting"""
    init_database()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Build UPDATE query dynamically
    set_clauses = []
    values = []
    
    for key, value in updates.items():
        if value is not None:
            set_clauses.append(f"{key} = ?")
            # Convert lists to JSON
            if isinstance(value, (list, dict)):
                value = json.dumps(value)
            values.append(value)
    
    if not set_clauses:
        conn.close()
        return False, "No updates provided"
    
    # Add updated_at
    set_clauses.append("updated_at = CURRENT_TIMESTAMP")
    
    query = f"UPDATE meetings SET {', '.join(set_clauses)} WHERE meeting_id = ?"
    values.append(meeting_id)
    
    cursor.execute(query, values)
    conn.commit()
    rows_affected = cursor.rowcount
    conn.close()
    
    return rows_affected > 0, rows_affected

def toggle_meeting_skip(meeting_id, skip_status: bool, title="Unknown Meeting", start_time=None):
    """
    Toggle whether the bot should skip this meeting.
    Creates meeting record if it doesn't exist.
    """
    init_database()
    status = 1 if skip_status else 0
    
    # Try updating first
    success, _ = update_meeting(meeting_id, {'is_skipped': status})
    
    if not success:
        # Meeting doesn't exist in DB yet, create skeleton record
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO meetings (meeting_id, title, start_time, is_skipped)
                VALUES (?, ?, ?, ?)
            ''', (meeting_id, title, start_time, status))
            conn.commit()
            success = True
        except Exception as e:
            print(f"Error upserting meeting skip: {e}")
            success = False
        finally:
            conn.close()
            
    return success

def set_meeting_bot_status(meeting_id, status, joined_at=None, status_note=None):
    """Update connection status, joined timestamp, and status note."""
    updates = {'bot_status': status}
    if joined_at:
        updates['bot_joined_at'] = joined_at
    if status_note:
        updates['bot_status_note'] = status_note
    return update_meeting(meeting_id, updates)

def get_active_joining_meeting():
    """Returns the first meeting that is currently JOINING or CONNECTED"""
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM meetings WHERE bot_status IN ('JOINING', 'CONNECTED') LIMIT 1")
        row = cursor.fetchone()
        return dict(row) if row else None

def get_meeting(meeting_id):
    """Get a specific meeting by ID"""
    init_database()
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM meetings WHERE meeting_id = ?", (meeting_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return dict(row)
    return None

def get_all_meetings(limit=50, offset=0, order_by='start_time DESC'):
    """Get all meetings with pagination"""
    init_database()
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    query = f"SELECT * FROM meetings ORDER BY {order_by} LIMIT ? OFFSET ?"
    cursor.execute(query, (limit, offset))
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]

def search_meetings(query, limit=20):
    """
    Search meetings by title or transcript content
    
    Args:
        query: Search term
        limit: Maximum results to return
    
    Returns:
        List of matching meetings
    """
    init_database()
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    search_pattern = f"%{query}%"
    
    cursor.execute('''
        SELECT * FROM meetings 
        WHERE title LIKE ? 
           OR transcript_text LIKE ? 
           OR summary_text LIKE ?
        ORDER BY start_time DESC
        LIMIT ?
    ''', (search_pattern, search_pattern, search_pattern, limit))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]

def get_meeting_stats():
    """Get statistics about meetings"""
    init_database()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    stats = {}
    
    # Total meetings
    cursor.execute("SELECT COUNT(*) FROM meetings")
    stats['total_meetings'] = cursor.fetchone()[0]
    
    # Total duration
    cursor.execute("SELECT SUM(duration_minutes) FROM meetings WHERE duration_minutes IS NOT NULL")
    total_minutes = cursor.fetchone()[0] or 0
    stats['total_duration_hours'] = round(total_minutes / 60, 1)
    
    # Average participants
    cursor.execute("SELECT AVG(participant_count) FROM meetings WHERE participant_count > 0")
    stats['avg_participants'] = round(cursor.fetchone()[0] or 0, 1)
    
    # Meetings this week
    cursor.execute('''
        SELECT COUNT(*) FROM meetings 
        WHERE start_time >= date('now', '-7 days')
    ''')
    stats['meetings_this_week'] = cursor.fetchone()[0]

    # Aggregated Metrics (Engagement & Words)
    cursor.execute("SELECT engagement_metrics FROM meetings WHERE engagement_metrics IS NOT NULL")
    eng_rows = cursor.fetchall()
    total_eng = 0
    total_words = 0
    for row in eng_rows:
        try:
            d = json.loads(row[0])
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
    cursor.execute('''
        SELECT speaker_analytics FROM meetings 
        WHERE speaker_analytics IS NOT NULL 
        ORDER BY start_time DESC 
        LIMIT 10
    ''')
    rows = cursor.fetchall()
    speaker_totals = {}
    for row in rows:
        try:
            data = json.loads(row[0])
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
    
    conn.close()
    return stats

def save_meeting_results(meeting_id, transcript, summary, action_items, speaker_stats, engagement):
    """Save final AI intelligence and analytics to the DB"""
    updates = {
        'transcript_text': transcript,
        'summary_text': summary,
        'action_items': action_items,
        'speaker_analytics': speaker_stats,
        'engagement_metrics': engagement,
        'status': 'completed'
    }
    return update_meeting(meeting_id, updates)

# --- WORKSPACE OPERATIONS (Restored & Enhanced) ---

def create_workspace(name, owner_email, description=None):
    """Create a new organization workspace with a unique shareable ID"""
    import secrets
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    workspace_id = ""
    # Ensure uniqueness
    for _ in range(10):
        workspace_id = secrets.token_hex(4).upper() # 8 characters
        cursor.execute("SELECT id FROM workspaces WHERE id = ?", (workspace_id,))
        if not cursor.fetchone():
            break
            
    try:
        cursor.execute(
            "INSERT INTO workspaces (id, name, owner_email, description) VALUES (?, ?, ?, ?)",
            (workspace_id, name, owner_email, description)
        )
        # Add owner as first member
        cursor.execute(
            "INSERT INTO workspace_members (workspace_id, user_email, role) VALUES (?, ?, 'owner')",
            (workspace_id, owner_email)
        )
        conn.commit()
        conn.close()
        return True, workspace_id
    except sqlite3.Error as e:
        conn.close()
        return False, str(e)

def join_workspace(workspace_id, email):
    """Join an existing workspace using its unique ID"""
    workspace_id = workspace_id.strip().upper()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        # Verify workspace exists
        cursor.execute("SELECT id FROM workspaces WHERE id = ?", (workspace_id,))
        if not cursor.fetchone():
            conn.close()
            return False, "Workspace not found. Check the ID."
            
        cursor.execute(
            "INSERT INTO workspace_members (workspace_id, user_email, role) VALUES (?, ?, 'member')",
            (workspace_id, email)
        )
        conn.commit()
        conn.close()
        return True, "Joined successfully!"
    except sqlite3.IntegrityError:
        conn.close()
        return False, "You are already a member of this workspace."
    except sqlite3.Error as e:
        conn.close()
        return False, str(e)

def get_user_workspaces(email):
    """Get all workspaces a user belongs to"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('''
        SELECT w.*, wm.role 
        FROM workspaces w
        JOIN workspace_members wm ON w.id = wm.workspace_id
        WHERE wm.user_email = ?
    ''', (email,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_workspace_members(workspace_id):
    """List all members of a workspace"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT user_email, role, joined_at FROM workspace_members WHERE workspace_id = ?", (workspace_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def send_workspace_message(workspace_id, sender_email, sender_name, message, attachment_path=None, attachment_name=None):
    """Send a message to workspace chat"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO workspace_chats 
            (workspace_id, sender_email, sender_name, message, attachment_path, attachment_name)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (workspace_id, sender_email, sender_name, message, attachment_path, attachment_name))
        conn.commit()
        conn.close()
        return True
    except sqlite3.Error:
        conn.close()
        return False

def get_workspace_messages(workspace_id, limit=50):
    """Get recent messages from workspace chat"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM workspace_chats 
        WHERE workspace_id = ? 
        ORDER BY created_at ASC 
        LIMIT ?
    ''', (workspace_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

# --- LIVE MEETING INJECTOR ---
def inject_bot_now(url):
    """
    Directly spawns a bot to a URL. 
    Replicates 'Add to live meeting' (Screenshot 5).
    """
    import subprocess
    import sys
    try:
        # Launch using the existing pilot script
        subprocess.Popen([sys.executable, "renata_bot_pilot.py", url])
        return True, "Bot is joining the live meeting..."
    except Exception as e:
        return False, str(e)

# --- ASSISTANT CHAT HISTORY OPERATIONS ---

def create_assistant_thread(user_email, title="New Conversation"):
    """Create a new personal chat thread for the assistant"""
    import secrets
    thread_id = secrets.token_hex(8).upper()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO assistant_threads (id, user_email, title) VALUES (?, ?, ?)",
            (thread_id, user_email, title)
        )
        conn.commit()
        conn.close()
        return thread_id
    except sqlite3.Error:
        conn.close()
        return None

def save_assistant_message(thread_id, role, content):
    """Save a single message to a chat thread"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO assistant_messages (thread_id, role, content) VALUES (?, ?, ?)",
            (thread_id, role, content)
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.Error:
        conn.close()
        return False

def get_user_assistant_threads(user_email):
    """Get all chat threads for a specific user"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM assistant_threads WHERE user_email = ? ORDER BY created_at DESC", (user_email,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_assistant_thread_messages(thread_id):
    """Get all messages for a specific chat thread"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT role, content FROM assistant_messages WHERE thread_id = ? ORDER BY created_at ASC", (thread_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def update_assistant_thread_title(thread_id, new_title):
    """Update conversation title (first few words of first user message)"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE assistant_threads SET title = ? WHERE id = ?", (new_title, thread_id))
        conn.commit()
        conn.close()
        return True
    except:
        conn.close()
        return False

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
    
    print(f"✅ Added meeting: {success}, ID: {meeting_id}")
    
    # Get stats
    stats = get_meeting_stats()
    print(f"\n📊 Stats: {stats}")
    
    # Search
    results = search_meetings("project")
    print(f"\n🔍 Search results: {len(results)} meetings found")
