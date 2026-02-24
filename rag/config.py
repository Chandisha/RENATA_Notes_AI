import os
from pathlib import Path

class RAGConfig:
    """Configuration class for the RAG system adapted for Renata-meet"""
    
    # Storage Paths
    BASE_DIR = Path(__file__).parent.parent
    CHROMA_DB_PATH = os.path.join(BASE_DIR, "media", "rag", "vector_db")
    
    # Models
    EMBEDDING_MODEL = "all-MiniLM-L6-v2"
    LLM_MODEL = "gemma2"  # Using Local Ollama
    
    # Text Processing
    CHUNK_SIZE = 512
    CHUNK_OVERLAP = 100
    TEXT_SEPARATORS = ["\n\n", "\n", ". ", " ", ""]
    
    # Retrieval
    N_RESULTS = 10
    SIMILARITY_THRESHOLD = 0.25  # Balanced threshold to avoid complete noise
    
    # Memory
    MAX_HISTORY_TURNS = 10
    MAX_MEMORY_TOKEN_LIMIT = 4000
    
    # LLM Settings
    MAX_NEW_TOKENS = 1024
    TEMPERATURE = 0.0
    
    # Prompting
    SYSTEM_PROMPT = """You are Renata, an Advanced AI Meeting Assistant. 

CORE CAPABILITIES:
1. REPORT ANALYSIS: You can answer questions about meeting reports stored in your memory.
2. GENERAL ASSISTANCE: You can greet users, explain what you can do, and help them navigate the platform.

RULES FOR MEETING DATA:
- If a user asks about meetings, use the provided document context.
- NO HALLUCINATIONS: Do not make up facts about meetings if not found in the documents.
- FILENAMES: Every chunk starts with "FILENAME:". Use this to identify the meeting.

RULES FOR GENERAL CHAT:
- If the user says "Hi", "Hello", or asks "What can you do?", answer in exactly one short, friendly sentence.
- Example: "Hi! I'm Renata, and I can help you find any information from your meeting reports."
"""
    
    REWRITE_SYSTEM_PROMPT = """Rewrite the follow-up question as a standalone question that includes necessary context from the conversation history.
    Output ONLY the rewritten question."""
    
    REWRITE_MAX_TOKENS = 50
    REWRITE_TEMPERATURE = 0.1
    REWRITE_MAX_HISTORY = 4

    @classmethod
    def initialize(cls):
        """Ensure paths exist"""
        os.makedirs(cls.CHROMA_DB_PATH, exist_ok=True)
        os.makedirs(os.path.join(cls.BASE_DIR, "media", "rag"), exist_ok=True)
