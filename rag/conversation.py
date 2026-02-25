from typing import List, Dict, Tuple, Optional
import os
import time
from .config import RAGConfig
from .document_processor import DocumentProcessor
from .embeddings import EmbeddingManager
from .vector_store import VectorStore
from .llm_manager import LLMManager
from .retriever import Retriever

class RAGChatbot:
    """Orchestrates the RAG system for conversation"""
    
    def __init__(self, config: RAGConfig = None):
        self.config = config or RAGConfig()
        self.document_processor = DocumentProcessor(self.config)
        self.embedding_manager = EmbeddingManager(self.config)
        self.vector_store = VectorStore(self.config)
        self.llm_manager = LLMManager(self.config)
        self.retriever = None
        self.conversation_memory = {}
        self.is_initialized = False
    
    def initialize(self, reset: bool = False):
        """Initialize all components"""
        self.config.initialize()
        self.vector_store.initialize(reset=reset)
        self.embedding_manager.load_model()
        self.llm_manager.load_model()
        self.retriever = Retriever(
            embedding_manager=self.embedding_manager,
            vector_store=self.vector_store,
            llm_manager=self.llm_manager,
            config=self.config
        )
        self.is_initialized = True
        print("RAG System initialized")
        
    def index_documents(self, directory_path: str, files: List[str] = None):
        """Index all or specific files in a directory"""
        if not self.is_initialized:
            self.initialize()
            
        print(f"Indexing files from: {directory_path} (Files: {files if files else 'All'})")
        
        chunks = []
        if files:
            import os
            for f in files:
                file_path = os.path.join(directory_path, f)
                if os.path.exists(file_path):
                    chunks.extend(self.document_processor.process_file(file_path))
        else:
            chunks = self.document_processor.load_directory(directory_path)
        
        if not chunks:
            print("No valid content found to index")
            return
            
        texts = [c.page_content for c in chunks]
        metadatas = [c.metadata for c in chunks]
        
        embeddings = self.embedding_manager.generate_embeddings(texts)
        
        self.vector_store.add_documents(
            embeddings=embeddings,
            texts=texts,
            metadatas=metadatas
        )
        print(f"Indexed {len(chunks)} chunks")
        
    def query(self, question: str, thread_id: str = "default", filter_files: List[str] = None) -> Tuple[str, List[Dict]]:
        """Process a user query with optional file filtering"""
        if not self.is_initialized:
            self.initialize()
            
        # 1. Memory management
        history = self.conversation_memory.get(thread_id, [])
        
        # 2. Query Rewriting
        rewritten_question = self.llm_manager.rewrite_question(question, history)
        
        # 3. Handle Social Greetings/Capabilities first (No retrieval needed)
        is_social = any(word in question.lower().split() for word in ["hi", "hello", "hey", "who", "what", "help"])
        
        if is_social and not any(kw in question.lower() for kw in ["meeting", "report", "discuss", "decide", "action"]):
            messages = [{"role": "system", "content": self.config.SYSTEM_PROMPT}]
            messages.extend(history[-self.config.MAX_HISTORY_TURNS * 2:])
            prompt = f"Social Question: {question}\n\nTask: Answer in exactly one short, simple sentence as Renata. Tell the user you can help them search through and analyze their meeting reports."
            messages.append({"role": "user", "content": prompt})
            answer = self.llm_manager.generate(messages)
            self._update_memory(thread_id, question, answer)
            return answer, []

        # 4. Retrieval with Filtering (For actual data queries)
        # Construct Chroma filter if files specified
        where_filter = None
        if filter_files:
            if len(filter_files) == 1:
                where_filter = {"source": filter_files[0]}
            else:
                where_filter = {"source": {"$in": filter_files}}

        docs, metadatas, similarities = self.retriever.retrieve(rewritten_question, where=where_filter)
        
        # 5. Context Preparation
        context = ""
        sources = []
        if docs:
            # Filter by threshold
            relevant_indices = [i for i, s in enumerate(similarities) if s >= self.config.SIMILARITY_THRESHOLD]
            if relevant_indices:
                relevant_docs = [docs[i] for i in relevant_indices]
                context = self.retriever.format_context(relevant_docs)
                sources = self.retriever.prepare_sources(
                    [metadatas[i] for i in relevant_indices],
                    [similarities[i] for i in relevant_indices]
                )
        
        # 6. Generation (Knowledge-based)
        messages = [{"role": "system", "content": self.config.SYSTEM_PROMPT}]
        messages.extend(history[-self.config.MAX_HISTORY_TURNS * 2:])
        
        # Add current user prompt with context
        if context:
            prompt = f"--- MEETING DOCUMENTS CONTEXT ---\n{context}\n--- END CONTEXT ---\n\nUser Question: {question}\n\nTask: Using ONLY the context above, answer the question. If details aren't there, say you can't find them."
        else:
            # Check if we have any files at all
            meeting_dir = os.path.join(os.getcwd(), "meeting_outputs")
            files_exist = os.path.exists(meeting_dir) and (len(os.listdir(meeting_dir)) > 0)
            
            if not files_exist:
                return "I'm ready to help, but I don't see any meeting reports in my memory yet. Please record or upload a meeting first!", []
            
            prompt = f"Technical Question with No Matches: {question}\n\nTask: Tell the user you searched your memory but couldn't find a direct match. Ask them to be more specific."
            
        messages.append({"role": "user", "content": prompt})
        answer = self.llm_manager.generate(messages)
        self._update_memory(thread_id, question, answer)
        return answer, sources

    def _update_memory(self, thread_id: str, question: str, answer: str):
        """Helper to update conversation history"""
        if thread_id not in self.conversation_memory:
            self.conversation_memory[thread_id] = []
        self.session_state_msgs = self.conversation_memory[thread_id]
        self.session_state_msgs.append({"role": "user", "content": question})
        self.session_state_msgs.append({"role": "assistant", "content": answer})
