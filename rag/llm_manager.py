import os
from dotenv import load_dotenv
load_dotenv()
from typing import List, Dict, Optional
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, BaseMessage
from .config import RAGConfig

class LLMManager:
    """Manages LLM inference using Local Ollama"""
    
    def __init__(self, config: RAGConfig = None):
        self.config = config or RAGConfig()
        self.llm = None
    
    def load_model(self):
        """Initialize the ChatOllama client"""
        if self.llm is not None:
            return
            
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        
        self.llm = ChatOllama(
            model=self.config.LLM_MODEL,
            temperature=self.config.TEMPERATURE,
            num_predict=self.config.MAX_NEW_TOKENS,
            base_url=base_url
        )
        print(f"✅ LLM (Ollama: {self.config.LLM_MODEL}) initialized at {base_url}")
    
    def generate(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """Generate response from messages"""
        if self.llm is None:
            self.load_model()
            
        langchain_messages = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            if role == "user":
                langchain_messages.append(HumanMessage(content=content))
            elif role == "assistant":
                langchain_messages.append(AIMessage(content=content))
            elif role == "system":
                langchain_messages.append(SystemMessage(content=content))

        # Invoke model
        response = self.llm.invoke(langchain_messages, **kwargs)
        return response.content.strip()

    def rewrite_question(self, question: str, chat_history: List) -> str:
        """Rewrite follow-up question to be standalone"""
        if self.llm is None:
            self.load_model()
            
        if not chat_history:
            return question
            
        history_text = ""
        for msg in chat_history[-self.config.REWRITE_MAX_HISTORY:]:
            if isinstance(msg, dict):
                role = "Q" if msg.get('role') == 'user' else "A"
                history_text += f"{role}: {msg.get('content', '')[:100]}\n"

        messages = [
            SystemMessage(content=self.config.REWRITE_SYSTEM_PROMPT),
            HumanMessage(content=f"Context:\n{history_text}\nCurrent question: {question}\n\nRewritten standalone question:")
        ]

        try:
            rewritten = self.llm.invoke(messages, temperature=self.config.REWRITE_TEMPERATURE).content.strip()
            return rewritten.split('\n')[0].strip()
        except:
            return question
