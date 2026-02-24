import os
import json
import re
from typing import List, Dict, Optional
from pathlib import Path
import pdfplumber
from pypdf import PdfReader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from .config import RAGConfig

class DocumentProcessor:
    """Processes PDF and JSON documents for indexing with multi-layer extraction"""
    
    def __init__(self, config: RAGConfig = None):
        self.config = config or RAGConfig()
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.config.CHUNK_SIZE * 2,  # Bigger chunks for more context
            chunk_overlap=self.config.CHUNK_OVERLAP,
            length_function=len,
            separators=self.config.TEXT_SEPARATORS
        )

    def clean_text(self, text: str) -> str:
        """Fix CID issues and basic encoding cleanup"""
        if not text: return ""
        # Remove (cid:...) noise
        text = re.sub(r'\(cid:\d+\)', ' ', text)
        # Normalize whitespace
        text = " ".join(text.split())
        return text

    def extract_pdf_text(self, pdf_path: str) -> List[Dict]:
        """Extract text from PDF using multiple methods for reliability"""
        pages_data = []
        filename = Path(pdf_path).name
        
        # Try pdfplumber first
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages):
                    text = page.extract_text()
                    text = self.clean_text(text)
                    if not text or len(text) < 20: 
                        # Try pypdf fallback for this page
                        reader = PdfReader(pdf_path)
                        text = reader.pages[page_num].extract_text()
                        text = self.clean_text(text)
                    
                    if text:
                        # Rich header for every chunk
                        full_content = f"FILENAME: {filename}\nSOURCE_TYPE: PDF Report\nPAGE: {page_num + 1}\nCONTENT:\n{text}"
                        pages_data.append({
                            'page_number': page_num,
                            'text': full_content,
                            'source': filename
                        })
        except Exception as e:
            print(f"Error processing PDF {pdf_path}: {e}")
            # Global fallback to pypdf
            try:
                reader = PdfReader(pdf_path)
                for page_num, page in enumerate(reader.pages):
                    text = self.clean_text(page.extract_text())
                    if text:
                        full_content = f"FILENAME: {filename}\nSOURCE_TYPE: PDF Report (Fallback)\nPAGE: {page_num + 1}\nCONTENT:\n{text}"
                        pages_data.append({
                            'page_number': page_num,
                            'text': full_content,
                            'source': filename
                        })
            except: pass
            
        return pages_data

    def extract_json_data(self, json_path: str) -> List[Dict]:
        """Extract deep intelligence from RENA JSON files"""
        filename = Path(json_path).name
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            intelligence = data.get("intelligence", {})
            if not intelligence: return []
            
            # Extract distinct blocks for better vectorization
            blocks = []
            
            # 1. Summary Block
            summary = intelligence.get("summary_en", "")
            if summary:
                text = f"FILENAME: {filename}\nSOURCE_TYPE: Intelligence Summary\nSUMMARY:\n{summary}"
                blocks.append({'page_number': 0, 'text': text, 'source': filename})
            
            # 2. MOM Block
            mom = intelligence.get("mom", [])
            if mom:
                text = f"FILENAME: {filename}\nSOURCE_TYPE: Minutes of Meeting (MoM)\nPOINTS:\n" + "\n".join([f"- {item}" for item in mom])
                blocks.append({'page_number': 1, 'text': text, 'source': filename})
            
            # 3. Actions Block
            actions = intelligence.get("actions", [])
            if actions:
                text = f"FILENAME: {filename}\nSOURCE_TYPE: Action Items and Tasks\nTASKS:\n" + "\n".join([f"- {a.get('task')} [Owner: {a.get('owner')}] [Deadline: {a.get('deadline')}]" for a in actions])
                blocks.append({'page_number': 2, 'text': text, 'source': filename})
            
            # 4. Full transcript sample/intel (optional, but good for context)
            transcript = data.get("transcript", [])
            if transcript:
                # Just take the first few lines to give context of who talked
                sample = "\n".join([f"{t.get('speaker')}: {t.get('text')}" for t in transcript[:20]])
                text = f"FILENAME: {filename}\nSOURCE_TYPE: Transcript Sample\n{sample}"
                blocks.append({'page_number': 3, 'text': text, 'source': filename})

            return blocks
        except Exception as e:
            print(f"Error processing JSON {json_path}: {e}")
            return []
    
    def process_file(self, file_path: str) -> List[Document]:
        """Process file and return as list of documents"""
        path = Path(file_path)
        if path.suffix.lower() == '.pdf':
            pages = self.extract_pdf_text(file_path)
        elif path.suffix.lower() == '.json':
            pages = self.extract_json_data(file_path)
        else:
            return []
        
        documents = []
        for page in pages:
            # For JSON blocks, we don't necessarily want to split them further if they are concise
            if "Intelligence" in page['text'] or "Action Items" in page['text']:
                # Keep these as single chunks if possible
                doc = Document(
                    page_content=page['text'],
                    metadata={'source': page['source'], 'page': page['page_number']}
                )
                documents.append(doc)
            else:
                # Regular splitting for long text
                doc = Document(
                    page_content=page['text'],
                    metadata={'source': page['source'], 'page': page['page_number']}
                )
                split_docs = self.text_splitter.split_documents([doc])
                documents.extend(split_docs)
            
        return documents

    def load_directory(self, directory_path: str) -> List[Document]:
        """Scan directory and load all valid formats"""
        all_chunks = []
        path = Path(directory_path)
        if not path.exists(): return []
            
        # Support both formats
        files = list(path.glob("*.pdf")) + list(path.glob("*.json"))
        
        for f in files:
            chunks = self.process_file(str(f))
            all_chunks.extend(chunks)
            
        print(f"Processed {len(files)} files. Generated {len(all_chunks)} chunks.")
        return all_chunks
