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
        
        # Find the meeting record that matches this filename
        meeting = db.fetch_one("SELECT meeting_id, pdf_blob FROM meetings WHERE pdf_path LIKE ?", (f"%{pdf_name}%",))
        
        if meeting:
            if meeting.get('pdf_blob'):
                print(f"Skipping {pdf_name} - already synced.")
                continue
                
            print(f"Syncing {pdf_name}...")
            try:
                with open(pdf_path, "rb") as f:
                    blob = base64.b64encode(f.read()).decode('utf-8')
                
                db.exec_commit("UPDATE meetings SET pdf_blob = ? WHERE meeting_id = ?", (blob, meeting['meeting_id']))
                print(f"Success: {pdf_name} is now available on Vercel Dashboard.")
            except Exception as e:
                print(f"Error syncing {pdf_name}: {e}")
        else:
            # print(f"No DB record found for {pdf_name}")
            pass

if __name__ == "__main__":
    sync_existing_pdfs()
