import os.path
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

# Scopes define what the AI is allowed to do. 
# We only need to READ the calendar to see upcoming meetings.
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

def register():
    creds = None
    # Check if we already have a token
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    # If no valid token, let's create one
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # This looks for your renamed 'credentials.json'
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Save the token for future use
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    
    print("SUCCESS: You are now registered!")
    print("'token.json' has been created in your folder.")

if __name__ == "__main__":
    register()