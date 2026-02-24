from typing import List, Dict, Tuple, Optional
from .config import RAGConfig
from .embeddings import EmbeddingManager
from .vector_store import VectorStore
from .llm_manager import LLMManager

class Retriever:
    """Manages retrieval of relevant document chunks"""
    
    def __init__(self, embedding_manager: EmbeddingManager,
                 vector_store: VectorStore,
                 llm_manager: LLMManager = None,
                 config: RAGConfig = None):
        self.embedding_manager = embedding_manager
        self.vector_store = vector_store
        self.llm_manager = llm_manager
        self.config = config or RAGConfig()
    
    def retrieve(self, query: str, n_results: int = None, where: Dict = None) -> Tuple[List[str], List[Dict], List[float]]:
        """Retrieve relevant chunks for a query"""
        # 1. Rewrite query if history exists (handled in conversation.py)
        
        # 2. Generate embedding
        query_embedding = self.embedding_manager.generate_query_embedding(query)
        
        # 3. Search vector store
        n = n_results or self.config.N_RESULTS
        results = self.vector_store.query(query_embedding, n_results=n, where=where)
        
        # 4. Extract results
        if not results['documents'] or not results['documents'][0]:
            return [], [], []
            
        docs = results['documents'][0]
        metadatas = results['metadatas'][0]
        distances = results['distances'][0]
        
        # Convert Squared L2 distances to standard similarity scores
        # For normalized vectors: dist_sq = 2 - 2*cos_sim => cos_sim = 1 - (dist_sq / 2)
        similarities = [1 - (d / 2.0) for d in distances]
        
        return docs, metadatas, similarities
    
    def format_context(self, documents: List[str]) -> str:
        """Format retrieved documents into a single context string"""
        return "\n\n".join(documents)
    
    def prepare_sources(self, metadatas: List[Dict], similarities: List[float]) -> List[Dict]:
        """Format metadata and scores into source list"""
        sources = []
        for meta, sim in zip(metadatas, similarities):
            sources.append({
                'source': meta.get('source', 'Unknown'),
                'page': meta.get('page', 0) + 1,
                'similarity': round(sim, 3)
            })
        return sources
