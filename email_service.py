"""
Email Service for RENA Bot
Sends meeting summaries to participants via Gmail API
Replicates Read.ai's email notification feature
"""
import os
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

SCOPES = ['https://www.googleapis.com/auth/gmail.send']

def get_gmail_service():
    """Get Gmail API service using existing token"""
    if not os.path.exists('token.json'):
        raise Exception("token.json not found. Please authorize first.")
    
    # Try to use existing token (it has calendar scope, we need to add gmail scope)
    # For now, we'll use the calendar token and see if it works
    # If not, user will need to re-authorize with gmail scope
    creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    service = build('gmail', 'v1', credentials=creds)
    return service

def create_meeting_summary_email(
    to_emails,
    meeting_title,
    meeting_date,
    meeting_duration,
    summary_text,
    pdf_path=None
):
    """
    Create a professional meeting summary email
    
    Args:
        to_emails: List of recipient email addresses
        meeting_title: Title of the meeting
        meeting_date: Date/time of meeting
        meeting_duration: Duration string (e.g., "45 minutes")
        summary_text: Brief summary text
        pdf_path: Optional path to PDF attachment
    """
    message = MIMEMultipart()
    message['To'] = ', '.join(to_emails) if isinstance(to_emails, list) else to_emails
    message['Subject'] = f"📝 Meeting Notes: {meeting_title}"
    
    # HTML email body
    html_body = f"""
    <html>
    <head>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 10px 10px 0 0; text-align: center; }}
            .header h1 {{ margin: 0; font-size: 24px; }}
            .content {{ background: #ffffff; padding: 30px; border: 1px solid #e1e8ed; border-top: none; }}
            .meeting-info {{ background: #f8f9fa; padding: 15px; border-radius: 8px; margin: 20px 0; }}
            .meeting-info p {{ margin: 8px 0; }}
            .summary-box {{ background: #e8f4f8; border-left: 4px solid #3b82f6; padding: 15px; margin: 20px 0; }}
            .footer {{ text-align: center; padding: 20px; color: #64748b; font-size: 12px; }}
            .button {{ display: inline-block; background: #667eea; color: white; padding: 12px 30px; text-decoration: none; border-radius: 6px; margin: 10px 0; }}
            .badge {{ display: inline-block; background: #10b981; color: white; padding: 4px 12px; border-radius: 12px; font-size: 11px; font-weight: bold; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🤖 RENA Meeting Notes</h1>
                <p style="margin: 10px 0 0 0; opacity: 0.9;">Your AI Meeting Assistant</p>
            </div>
            
            <div class="content">
                <p>Hi there! 👋</p>
                <p>RENA has finished processing your meeting. Here's what was discussed:</p>
                
                <div class="meeting-info">
                    <p><strong>📅 Meeting:</strong> {meeting_title}</p>
                    <p><strong>🕐 Date:</strong> {meeting_date}</p>
                    <p><strong>⏱️ Duration:</strong> {meeting_duration}</p>
                    <p><span class="badge">✅ PROCESSED</span></p>
                </div>
                
                <div class="summary-box">
                    <h3 style="margin-top: 0; color: #1e40af;">📝 Quick Summary</h3>
                    <p>{summary_text}</p>
                </div>
                
                <p><strong>📎 Attached:</strong> Complete meeting notes with transcript, action items, and detailed summary</p>
                
                <p style="margin-top: 30px;">
                    <em>This meeting was recorded and transcribed by RENA AI. All participants were notified at the start of the meeting.</em>
                </p>
            </div>
            
            <div class="footer">
                <p>Powered by RENA AI | Meeting Intelligence Platform</p>
                <p>Questions? Contact your workspace administrator</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    message.attach(MIMEText(html_body, 'html'))
    
    # Attach PDF if provided
    if pdf_path and os.path.exists(pdf_path):
        with open(pdf_path, 'rb') as f:
            pdf_attachment = MIMEApplication(f.read(), _subtype='pdf')
            pdf_attachment.add_header('Content-Disposition', 'attachment', 
                                    filename=os.path.basename(pdf_path))
            message.attach(pdf_attachment)
    
    return message

def send_email(service, message, sender_email='me'):
    """Send email via Gmail API"""
    try:
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        send_message = {'raw': raw_message}
        
        result = service.users().messages().send(
            userId=sender_email,
            body=send_message
        ).execute()
        
        return True, result['id']
    except Exception as e:
        return False, str(e)

def send_meeting_summary(
    recipient_emails,
    meeting_title,
    meeting_date,
    meeting_duration,
    summary_text,
    pdf_path=None
):
    """
    Main function to send meeting summary email
    
    Returns: (success: bool, message: str)
    """
    try:
        service = get_gmail_service()
        
        email_message = create_meeting_summary_email(
            to_emails=recipient_emails,
            meeting_title=meeting_title,
            meeting_date=meeting_date,
            meeting_duration=meeting_duration,
            summary_text=summary_text,
            pdf_path=pdf_path
        )
        
        success, result = send_email(service, email_message)
        
        if success:
            return True, f"Email sent successfully (ID: {result})"
        else:
            return False, f"Failed to send email: {result}"
            
    except Exception as e:
        return False, f"Error: {str(e)}"

def extract_participant_emails(calendar_event):
    """Extract email addresses from calendar event"""
    emails = []
    
    # Get organizer email
    organizer = calendar_event.get('organizer', {})
    if 'email' in organizer:
        emails.append(organizer['email'])
    
    # Get attendee emails
    attendees = calendar_event.get('attendees', [])
    for attendee in attendees:
        if 'email' in attendee:
            email = attendee['email']
            if email not in emails:  # Avoid duplicates
                emails.append(email)
    
    return emails

# Example usage
if __name__ == "__main__":
    # Test email sending
    test_recipients = ["test@example.com"]
    
    success, message = send_meeting_summary(
        recipient_emails=test_recipients,
        meeting_title="Weekly Team Sync",
        meeting_date="February 8, 2026 at 2:00 PM",
        meeting_duration="45 minutes",
        summary_text="Discussed project timeline, assigned action items, and reviewed Q1 goals. Team agreed to increase sprint velocity.",
        pdf_path=None
    )
    
    print(f"{'✅' if success else '❌'} {message}")
