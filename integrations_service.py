"""
Integrations Service for Renata Bot
Handles functional connections to external platforms like Notion, Drive, and Gmail
Replicates Read.ai's 'Supercharge Your Workflow' integrations
"""
import os
import json
import requests
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

class IntegrationManager:
    def __init__(self, token_path='token.json'):
        self.token_path = token_path
        self.creds = None
        if os.path.exists(token_path):
            self.creds = Credentials.from_authorized_user_file(token_path)

    def _reload_creds(self):
        """Reload credentials from disk to catch updates (e.g., new scopes)"""
        if os.path.exists(self.token_path):
            self.creds = Credentials.from_authorized_user_file(self.token_path)

    # --- GOOGLE DRIVE INTEGRATION ---
    def search_drive_files(self, query):
        """Search your Google Drive for context (replicates Drive integration)"""
        self._reload_creds()
        if not self.creds: return "Not connected"
        try:
            from googleapiclient.discovery import build
            service = build('drive', 'v3', credentials=self.creds)
            results = service.files().list(
                q=f"name contains '{query}'",
                pageSize=5, fields="files(id, name, mimeType)").execute()
            return results.get('files', [])
        except Exception as e:
            return f"Drive error: {str(e)}"

    # --- GMAIL INTEGRATION (INBOX SUMMARIES) ---
    def summarize_emails(self, max_results=5):
        """Fetch and briefly summarize recent important emails"""
        self._reload_creds()
        if not self.creds: return "Not connected"
        try:
            from googleapiclient.discovery import build
            service = build('gmail', 'v1', credentials=self.creds)
            results = service.users().messages().list(userId='me', maxResults=max_results).execute()
            messages = results.get('messages', [])
            
            summaries = []
            for msg in messages:
                txt = service.users().messages().get(userId='me', id=msg['id']).execute()
                snippet = txt.get('snippet', '')
                summaries.append(snippet)
            return summaries
        except Exception as e:
            # Handle rate limit (429) gracefully
            if "429" in str(e):
                return "**Gmail Rate Limit Exceeded:** You have fetched highlights too many times recently. Please wait about 30-60 minutes before trying again. Google has temporarily paused requests for your safety."
            raise e

    # --- ZOOM INTEGRATION ---
    def fetch_zoom_meetings(self, zoom_token):
        """Fetch upcoming meetings directly from Zoom account"""
        if not zoom_token: return "Zoom not connected"
        url = "https://api.zoom.us/v2/users/me/meetings"
        headers = {"Authorization": f"Bearer {zoom_token}"}
        try:
            resp = requests.get(url, headers=headers)
            if resp.status_code == 200:
                meetings = resp.json().get('meetings', [])
                return [{"title": m['topic'], "start": m['start_time'], "url": m['join_url']} for m in meetings]
            return f"Zoom API Error: {resp.status_code}"
        except Exception as e:
            return f"Zoom connection error: {str(e)}"

from datetime import datetime
# Singleton for reuse
integrations = IntegrationManager()
