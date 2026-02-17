"""
Integrations Service for RENA Bot
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

    # --- NOTION INTEGRATION ---
    def push_to_notion(self, title, summary, token, db_id):
        """Push meeting reports to a Notion database"""
        if not token or not db_id: return False, "Missing configuration"
        url = "https://api.notion.com/v1/pages"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28"
        }
        data = {
            "parent": {"database_id": db_id},
            "properties": {
                "Name": {"title": [{"text": {"content": title}}]},
                "Summary": {"rich_text": [{"text": {"content": summary[:2000]}}]}
            }
        }
        try:
            resp = requests.post(url, headers=headers, json=data)
            if resp.status_code == 200: return True, "Synced to Notion!"
            return False, f"Notion Error: {resp.text}"
        except Exception as e:
            return False, str(e)

    # --- HUBSPOT INTEGRATION ---
    def sync_to_hubspot(self, title, summary, api_key):
        """Push meeting intelligence to HubSpot CRM as a Note"""
        if not api_key: return False, "Missing HubSpot API Key"
        url = "https://api.hubapi.com/crm/v3/objects/notes"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "properties": {
                "hs_note_body": f"<b>RENA AI Summary: {title}</b><br>{summary}",
                "hs_timestamp": datetime.now().isoformat() + "Z"
            }
        }
        try:
            resp = requests.post(url, headers=headers, json=data)
            if resp.status_code == 201: return True, "Exported to HubSpot!"
            return False, f"HubSpot Error: {resp.text}"
        except Exception as e:
            return False, str(e)

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
            raise e

from datetime import datetime
# Singleton for reuse
integrations = IntegrationManager()
