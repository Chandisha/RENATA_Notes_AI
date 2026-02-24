import numpy as np
import torch
from typing import List, Dict, Optional
from sentence_transformers import SentenceTransformer
from .config import RAGConfig

class EmbeddingManager:
    """Manages embedding generation using SentenceTransformers"""
    
    def __init__(self, config: RAGConfig = None):
        self.config = config or RAGConfig()
        self.model = None
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
    
    def load_model(self):
        """Load the embedding model"""
        if self.model is not None:
            return
        
        print(f"🔄 Loading embedding model: {self.config.EMBEDDING_MODEL}")
        self.model = SentenceTransformer(
            self.config.EMBEDDING_MODEL,
            device=self.device,
            trust_remote_code=True
        )
        print(f"✅ Embedding model loaded")
    
    def generate_embeddings(self, texts: List[str], show_progress: bool = True) -> np.ndarray:
        """Generate embeddings for a list of texts"""
        if self.model is None:
            self.load_model()
        
        embeddings = self.model.encode(
            texts,
            show_progress_bar=show_progress,
            normalize_embeddings=True,
            convert_to_numpy=True
        )
        return embeddings
    
    def generate_query_embedding(self, query: str) -> np.ndarray:
        """Generate embedding for a single query"""
        if self.model is None:
            self.load_model()
        
        embedding = self.model.encode(
            query,
            normalize_embeddings=True,
            convert_to_numpy=True
        )
        return embedding
