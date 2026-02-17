"""
Search Assistant Service for RENA Bot
Provides AI-powered answers across multiple meetings using RAG logic
Replicates Read.ai's "Ask Search Assistant anything" feature
"""
import sqlite3
import json
import os
from pathlib import Path
from meeting_database import DB_PATH
import meeting_notes_generator

class SearchAssistant:
    def __init__(self):
        self.db_path = DB_PATH
    
    def get_relevant_transcripts(self, query, limit=5):
        """Find the most relevant meeting transcripts for a query"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Simple weighted search: prioritize exact matches in title or transcript
        search_pattern = f"%{query}%"
        cursor.execute('''
            SELECT title, transcript_text, summary_text, start_time 
            FROM meetings 
            WHERE title LIKE ? OR transcript_text LIKE ? OR summary_text LIKE ?
            ORDER BY start_time DESC
            LIMIT ?
        ''', (search_pattern, search_pattern, search_pattern, limit))
        
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def ask(self, question):
        """
        Hyper-Intelligence Assistant (RAG + General AI).
        Behaves like ChatGPT/Gemini but with meeting-specific knowledge.
        """
        # 1. Attempt to find matching meeting context
        relevant_data = self.get_relevant_transcripts(question)
        
        context_parts = []
        if relevant_data:
            for meeting in relevant_data:
                part = f"--- MEETING: {meeting['title']} ({meeting['start_time']}) ---\n"
                part += f"Summary: {meeting['summary_text'][:500]}...\n"
                part += f"Transcript Snippet: {meeting['transcript_text'][:1500]}...\n"
                context_parts.append(part)
        
        full_context = "\n\n".join(context_parts) if context_parts else "No specific matching meetings found in local history."
        
        # 2. Hybrid Prompt (General Knowledge + Meeting Context)
        prompt = f"""
        You are RENA AI, a professional and helpful intelligence assistant powered by Gemini. 
        You function as both a general-purpose AI (like ChatGPT) and a specialized Meeting Search Assistant.
        
        USER QUESTION: "{question}"
        
        MEETING KNOWLEDGE BASE (RAG):
        {full_context}
        
        INSTRUCTIONS:
        1. If the user is just chatting (e.g., "Hi", "How are you?"), respond as a helpful AI assistant.
        2. If the user asks about meetings, use the provided MEETING KNOWLEDGE BASE to give specific answers (including titles and dates).
        3. If the user asks a general question, answer it using your broad AI knowledge.
        4. If they ask about a meeting you don't have records for, answer what you can generally, then mention you don't see those specific meeting notes in the provided context.
        5. Stay concise, professional, and helpful.
        """
        
        try:
            from meeting_notes_generator import GEMINI_API_KEY
            from google import genai
            
            # Check environment variable first (as set by user), then fallback to hardcoded
            api_key = os.getenv("GEMINI_API_KEY", GEMINI_API_KEY)
            
            if not api_key or api_key == "YOUR_OWN_GOOGLE_API_KEY":
                return "⚠️ Search Assistant Error: Gemini API key is missing. Please set the GEMINI_API_KEY environment variable or configured it in meeting_notes_generator.py"

            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )
            return response.text
        except Exception as e:
            return f"❌ Search Assistant (Gemini) Error: {str(e)}"

# Singleton for reuse
assistant = SearchAssistant()

if __name__ == "__main__":
    # Test case
    print("🤖 Search Assistant Test Run")
    ans = assistant.ask("What were the latest action items discussed regarding the project?")
    print(f"\nCOPILOT ANSWER:\n{ans}")
