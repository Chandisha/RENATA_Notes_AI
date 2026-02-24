import chromadb
from typing import List, Dict, Tuple
from .config import RAGConfig

class VectorStore:
    """Manages vector database operations using ChromaDB"""
    
    def __init__(self, config: RAGConfig = None):
        self.config = config or RAGConfig()
        self.client = None
        self.collection = None
        # Default collection name if not set in config
        self.collection_name = getattr(self.config, 'COLLECTION_NAME', 'rena_meetings_v1')
    
    def initialize(self, db_path: str = None, reset: bool = False):
        """Initialize ChromaDB client and collection"""
        path = db_path or self.config.CHROMA_DB_PATH
        
        print(f"Initializing ChromaDB at: {path}")
        self.client = chromadb.PersistentClient(path=path)
        
        if reset:
            try:
                self.client.delete_collection(name=self.collection_name)
            except:
                pass
        
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"description": "RENA meeting embeddings"}
        )
        print(f"✅ Collection '{self.collection_name}' ready")
    
    def add_documents(self, embeddings: List[List[float]], texts: List[str], metadatas: List[Dict], ids: List[str] = None):
        """Add documents to the vector store"""
        if self.collection is None:
            self.initialize()
        
        if ids is None:
            import uuid
            ids = [str(uuid.uuid4()) for _ in range(len(texts))]
        
        self.collection.add(
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,
            ids=ids
        )
        print(f"✅ Added {len(texts)} chunks. Total: {self.collection.count()}")
    
    def query(self, query_embedding: List[float], n_results: int = None, where: Dict = None) -> Dict:
        """Query for similar documents"""
        if self.collection is None:
            self.initialize()
        
        if n_results is None:
            n_results = self.config.N_RESULTS
        
        # Ensure query_embedding is a list
        if hasattr(query_embedding, 'tolist'):
            query_embedding = query_embedding.tolist()
            
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=['documents', 'metadatas', 'distances'],
            where=where
        )
        return results

    def get_document_count(self) -> int:
        return self.collection.count() if self.collection else 0
