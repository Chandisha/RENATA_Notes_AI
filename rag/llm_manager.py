import os
from dotenv import load_dotenv
load_dotenv()
from typing import List, Dict, Optional
from .config import RAGConfig

class LLMManager:
    """Manages LLM inference using Google Gemini API"""
    
    def __init__(self, config: RAGConfig = None):
        self.config = config or RAGConfig()
        self.model = None
    
    def load_model(self):
        """Initialize the Gemini client"""
        if self.model is not None:
            return
            
        import google.generativeai as genai
        
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set in .env file")
        
        genai.configure(api_key=api_key)
        
        # Try models in priority order
        model_names = [
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
        ]
        
        for model_name in model_names:
            try:
                self.model = genai.GenerativeModel(model_name)
                # Quick validation
                self.model_name = model_name
                print(f"LLM (Gemini: {model_name}) initialized")
                return
            except Exception:
                continue
        
        raise RuntimeError("No Gemini model available. Check your API key.")
    
    def generate(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """Generate response from messages"""
        if self.model is None:
            self.load_model()
        
        # Convert chat messages to Gemini format
        # Gemini uses a simpler format: combine system + history into a single prompt
        system_prompt = ""
        conversation_parts = []
        
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")
            if role == "system":
                system_prompt = content
            elif role == "user":
                conversation_parts.append(f"User: {content}")
            elif role == "assistant":
                conversation_parts.append(f"Assistant: {content}")
        
        # Build final prompt
        full_prompt = ""
        if system_prompt:
            full_prompt += f"System Instructions: {system_prompt}\n\n"
        full_prompt += "\n".join(conversation_parts)
        
        try:
            response = self.model.generate_content(full_prompt)
            return response.text.strip()
        except Exception as e:
            return f"Gemini Error: {str(e)}"

    def rewrite_question(self, question: str, chat_history: List) -> str:
        """Rewrite follow-up question to be standalone"""
        if self.model is None:
            self.load_model()
            
        if not chat_history:
            return question
            
        history_text = ""
        for msg in chat_history[-self.config.REWRITE_MAX_HISTORY:]:
            if isinstance(msg, dict):
                role = "Q" if msg.get('role') == 'user' else "A"
                history_text += f"{role}: {msg.get('content', '')[:100]}\n"

        prompt = f"""{self.config.REWRITE_SYSTEM_PROMPT}

Context:
{history_text}
Current question: {question}

Rewritten standalone question:"""

        try:
            response = self.model.generate_content(prompt)
            rewritten = response.text.strip()
            return rewritten.split('\n')[0].strip()
        except:
            return question
