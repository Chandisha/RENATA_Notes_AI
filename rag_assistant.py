import os
from typing import List, Dict, Optional
from pathlib import Path
from rag import RAGChatbot, RAGConfig

class MeetingRAGAssistant:
    """Interface for the RAG chatbot in the Renata-meet project"""
    
    def __init__(self):
        self.config = RAGConfig()
        self.chatbot = RAGChatbot(self.config)
        self.is_indexed = False
        
    def _ensure_indexed(self, force_reset: bool = False, files: List[str] = None):
        """Initialization and indexing of meeting documents (PDF, JSON, or DB)"""
        db_exists = os.path.exists(self.config.CHROMA_DB_PATH)
        
        if not self.chatbot.is_initialized:
            should_reset = force_reset or not db_exists
            self.chatbot.initialize(reset=should_reset)
            
        meeting_dir = os.path.join(os.getcwd(), "meeting_outputs")
        if os.path.exists(meeting_dir) and len(os.listdir(meeting_dir)) > 0:
            if files:
                self.chatbot.index_documents(meeting_dir, files=files)
            elif force_reset or self.chatbot.vector_store.get_document_count() == 0:
                self.chatbot.index_documents(meeting_dir)
        else:
            # DB FALLBACK: Index from the main 'meetings' table
            if force_reset or self.chatbot.vector_store.get_document_count() == 0:
                print("Meeting outputs not found. Syncing from Database...")
                try:
                    import meeting_database as mdb
                    records = mdb.fetch_all("SELECT meeting_id, title, summary_text FROM meetings WHERE status = 'completed'")
                    for r in records:
                        text = f"MEETING: {r['title']}\nSUMMARY:\n{r['summary_text']}"
                        metadata = {'source': f"{r['meeting_id']}.db", 'page': 0}
                        # We need to manually add to vector store if we aren't using files
                        from langchain_core.documents import Document
                        doc = Document(page_content=text, metadata=metadata)
                        chunks = self.chatbot.document_processor.text_splitter.split_documents([doc])
                        
                        texts = [c.page_content for c in chunks]
                        metadatas = [c.metadata for c in chunks]
                        embeddings = self.chatbot.embedding_manager.generate_embeddings(texts)
                        self.chatbot.vector_store.add_documents(embeddings=embeddings, texts=texts, metadatas=metadatas)
                    print(f"Indexed {len(records)} previous meetings from DB.")
                except Exception as e:
                    print(f"DB Indexing Error: {e}")
        self.is_indexed = True

    def _get_filter_files(self, question: str) -> List[str]:
        """Auto-detect if user mentioned a specific document name"""
        meeting_dir = os.path.join(os.getcwd(), "meeting_outputs")
        if not os.path.exists(meeting_dir): return None
        
        all_files = os.listdir(meeting_dir)
        mentioned = []
        for f in all_files:
            # Check if filename (without extension usually mentioned) is in question
            base_name = os.path.splitext(f)[0]
            if base_name in question or f in question:
                mentioned.append(f)
        return mentioned if mentioned else None

    def ask(self, question: str, thread_id: str = "default", selected_files: List[str] = None) -> str:
        """Query the meeting documents with granular filtering"""
        try:
            # 1. Detect if files mentioned in prompt but not explicitly selected
            detected_files = self._get_filter_files(question)
            final_files = selected_files or detected_files
            
            # 2. Ensure mentioned files are indexed
            if final_files:
                self._ensure_indexed(files=final_files)
            else:
                self._ensure_indexed()

            # 3. Query with filter
            answer, sources = self.chatbot.query(question, thread_id=thread_id, filter_files=final_files)
            
            # Format answer with sources if available
            if sources:
                source_text = "\n\n**Sources:**\n"
                # Group by source to avoid duplicates and show pages
                source_groups = {}
                for s in sources:
                    name = s['source']
                    if name not in source_groups:
                        source_groups[name] = set()
                    source_groups[name].add(str(s['page']))
                
                for name, pages in source_groups.items():
                    pages_str = ", ".join(sorted(list(pages)))
                    source_text += f"- {name} (Pages: {pages_str})\n"
                return answer + source_text
            
            return answer
        except Exception as e:
            return f"RAG Assistant Error: {str(e)}"

# Singleton instance
assistant = MeetingRAGAssistant()

if __name__ == "__main__":
    # Test
    res = assistant.ask("What was discussed in the last meeting?")
    print(res)
