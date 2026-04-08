import os
import psycopg2
from dotenv import load_dotenv
from urllib.parse import urlparse
import socket

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def test_conn():
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not found in .env")
        return

    print(f"Testing connection to: {urlparse(DATABASE_URL).hostname}")
    
    try:
        # Step 1: DNS Resolution
        hostname = urlparse(DATABASE_URL).hostname
        print(f"1. DNS: Resolving {hostname}...")
        ip = socket.gethostbyname(hostname)
        print(f"   SUCCESS: IP is {ip}")
        
        # Step 2: TCP Connection
        print("2. TCP: Attempting connection to port 5432...")
        conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
        print("   SUCCESS: Connected to PostgreSQL!")
        
        # Step 3: Simple Query
        cur = conn.cursor()
        cur.execute("SELECT version();")
        print(f"3. QUERY: Server Version: {cur.fetchone()[0]}")
        
        conn.close()
    except Exception as e:
        print(f"!!! FAILURE: {e}")

if __name__ == "__main__":
    test_conn()
