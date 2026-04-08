"""
Renata - Local Token Refresh Tool
===================================
Run this once to re-authenticate with Google and save a fresh token
to your local database. This fixes the 'invalid_grant' error.

Usage: python refresh_token.py
"""
import os
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Only run on local SQLite (not Vercel)
if os.getenv("DATABASE_URL"):
    print("DATABASE_URL is set - you are using PostgreSQL.")
    print("Log in via the website at https://renata-notes-ai.vercel.app to refresh your token.")
    exit()

import meeting_database as db
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

SCOPES = [
    'openid',
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/drive.metadata.readonly'
]

CREDENTIALS_FILE = "credentials.json"

def refresh_local_token():
    if not Path(CREDENTIALS_FILE).exists():
        print(f"❌ ERROR: '{CREDENTIALS_FILE}' not found in project root.")
        print("Please download it from Google Cloud Console → APIs & Services → Credentials.")
        return

    print("🔑 Opening browser for Google Sign-In...")
    print("   Please log in with: renata@renataiot.com")
    print()

    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
    creds = flow.run_local_server(port=8765, prompt='consent')

    # Get user info
    import requests
    user_info_resp = requests.get(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        headers={"Authorization": f"Bearer {creds.token}"}
    )
    user_info = user_info_resp.json()
    email = user_info.get("email", "renata@renataiot.com")
    name = user_info.get("name", "User")

    print(f"\n✅ Authenticated as: {name} ({email})")

    # Save token to local SQLite DB
    token_json = creds.to_json()
    db.exec_commit("""
        INSERT INTO users (email, name, google_token, created_at, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(email) DO UPDATE SET
        google_token = excluded.google_token,
        name = excluded.name,
        updated_at = CURRENT_TIMESTAMP
    """, (email, name, token_json))

    print(f"✅ Fresh token saved to local database for {email}")
    print()
    print("🚀 You can now run: python renata_bot_pilot.py")

if __name__ == "__main__":
    refresh_local_token()
