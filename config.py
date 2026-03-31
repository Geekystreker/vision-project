import os

# Try to load python-dotenv if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

class Config:
    # Timeout limits
    API_TIMEOUT = 10
    
    # Optional Fallback Model properties
    OLLAMA_ENDPOINT = "http://localhost:11434/api/generate"
    OLLAMA_MODEL = "qwen3:1.7b"

