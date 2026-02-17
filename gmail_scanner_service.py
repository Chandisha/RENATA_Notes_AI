import os
import base64
import re
import meeting_database as db
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from datetime import datetime

class GmailScannerService:
    def __init__(self):
        self.scopes = ['https://www.googleapis.com/auth/gmail.readonly']
        self.keywords = {
            'deadline': [r'deadline', r'due date', r'by \d{1,2}/\d{1,2}', r'before \w+ \d{1,2}'],
            'project': [r'project', r'milestone', r'deliverable', r'roadmap'],
            'action_item': [r'action item', r'task', r'todo', r'to-do', r'assigned to']
        }

    def _get_service(self):
        if not os.path.exists('token.json'):
            return None
        creds = Credentials.from_authorized_user_file('token.json', self.scopes)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build('gmail', 'v1', credentials=creds)

    def scan_inbox(self, user_email, max_results=20):
        """Scan unread emails for keywords and save to DB"""
        service = self._get_service()
        if not service:
            return False, "Not authorized"

        try:
            # Fetch unread messages
            results = service.users().messages().list(userId='me', q='is:unread', maxResults=max_results).execute()
            messages = results.get('messages', [])

            found_count = 0
            for msg in messages:
                msg_data = service.users().messages().get(userId='me', id=msg['id']).execute()
                snippet = msg_data.get('snippet', '')
                subject = ""
                
                # Extract Subject
                headers = msg_data.get('payload', {}).get('headers', [])
                for h in headers:
                    if h['name'] == 'Subject':
                        subject = h['value']
                        break

                # Check keywords
                for category, patterns in self.keywords.items():
                    combined_text = (subject + " " + snippet).lower()
                    for pattern in patterns:
                        if re.search(pattern, combined_text):
                            # Save to DB
                            self._save_intelligence(user_email, msg['id'], category, subject, snippet)
                            found_count += 1
                            break
            
            return True, f"Scan complete. Found {found_count} insights."
        except Exception as e:
            return False, str(e)

    def _save_intelligence(self, email, msg_id, category, subject, snippet):
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO gmail_intelligence 
                (user_email, message_id, category, subject, snippet)
                VALUES (?, ?, ?, ?, ?)
            ''', (email, msg_id, category, subject, snippet))
            conn.commit()
        finally:
            conn.close()

    def get_latest_intelligence(self, user_email, limit=5):
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM gmail_intelligence 
            WHERE user_email = ? AND is_dismissed = 0
            ORDER BY created_at DESC LIMIT ?
        ''', (user_email, limit))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

gmail_scanner = GmailScannerService()
