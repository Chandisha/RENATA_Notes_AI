import os.path
import datetime
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

# Use the token you just created
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

def get_upcoming_meetings():
    if not os.path.exists('token.json'):
        print("❌ Error: token.json not found. Run register_calender.py first.")
        return

    creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    service = build('calendar', 'v3', credentials=creds)

    # Call the Calendar API
    now = datetime.datetime.utcnow().isoformat() + 'Z'  # 'Z' indicates UTC time
    print(f'📅 Fetching meetings starting from: {now}')
    
    events_result = service.events().list(calendarId='primary', timeMin=now,
                                        maxResults=5, singleEvents=True,
                                        orderBy='startTime').execute()
    events = events_result.get('items', [])

    if not events:
        print('No upcoming meetings found.')
        return

    print("\n--- YOUR UPCOMING MEETINGS ---")
    for event in events:
        start = event['start'].get('dateTime', event['start'].get('date'))
        print(f"🎬 {event['summary']} | Starts: {start}")

if __name__ == "__main__":
    get_upcoming_meetings()