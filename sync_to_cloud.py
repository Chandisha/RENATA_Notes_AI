import os
import base64
import meeting_database as db

def sync_existing_pdfs():
    print(">>> Syncing recent local PDFs to Cloud (Neon)...")
    meeting_outputs = "meeting_outputs"
    
    # Get all pdf files
    pdf_files = [f for f in os.listdir(meeting_outputs) if f.endswith(".pdf")]
    
    for pdf_name in pdf_files:
        pdf_path = os.path.join(meeting_outputs, pdf_name)
        
        # 1. Sync main PDF
        meeting = db.fetch_one("SELECT meeting_id, pdf_blob FROM meetings WHERE pdf_path LIKE ?", (f"%{pdf_name}%",))
        if meeting:
            if not meeting.get('pdf_blob'):
                print(f"Syncing {pdf_name}...")
                try:
                    with open(pdf_path, "rb") as f:
                        blob = base64.b64encode(f.read()).decode('utf-8')
                    db.exec_commit("UPDATE meetings SET pdf_blob = ? WHERE meeting_id = ?", (blob, meeting['meeting_id']))
                    print(f"Success: {pdf_name} is now available on Vercel Dashboard.")
                except Exception as e:
                    print(f"Error syncing {pdf_name}: {e}")
        
        # 2. Sync corresponding Transcripts PDF if it exists
        transcript_name = pdf_name.replace("Report_", "Transcripts_")
        transcript_path = os.path.join(meeting_outputs, transcript_name)
        if os.path.exists(transcript_path):
            meeting = db.fetch_one("SELECT meeting_id, transcripts_pdf_blob FROM meetings WHERE pdf_path LIKE ?", (f"%{pdf_name}%",))
            if meeting and not meeting.get('transcripts_pdf_blob'):
                print(f"Syncing {transcript_name}...")
                try:
                    with open(transcript_path, "rb") as f:
                        t_blob = base64.b64encode(f.read()).decode('utf-8')
                    db.exec_commit("UPDATE meetings SET transcripts_pdf_blob = ? WHERE meeting_id = ?", (t_blob, meeting['meeting_id']))
                    print(f"Success: {transcript_name} is now available on Vercel Dashboard.")
                except Exception as e:
                    print(f"Error syncing {transcript_name}: {e}")

if __name__ == "__main__":
    sync_existing_pdfs()
