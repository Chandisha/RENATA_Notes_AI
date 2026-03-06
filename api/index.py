import os
import sys

# Get the path to the project root (one level up from /api)
root_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, root_path)

# Now we can import main from the root
try:
    from main import app
except ImportError as e:
    print(f"Import Error: {e}")
    # Fallback/Debug info for Vercel logs
    print(f"Python Path: {sys.path}")
    print(f"Files in root: {os.listdir(root_path)}")
    raise e
