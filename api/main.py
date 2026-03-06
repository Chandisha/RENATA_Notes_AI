import os
import sys
from pathlib import Path

# Fix paths so we can import from the root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import the app instance directly
from main import app
