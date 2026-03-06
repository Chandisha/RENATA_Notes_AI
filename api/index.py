import os
import sys

# Add root directory to path so main.py and other modules can be imported
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app

# For Vercel, the app must be named 'app' in the entry point file
# or we can use the handler pattern
def handler(request):
    """Vercel entry point"""
    return app(request)

# Actually, Vercel's @vercel/python detects FastAPI app named 'app' automatically
# But we need it to be at the top level of the module it imports
from main import app
