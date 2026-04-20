import os
import subprocess
import sys

def run_cmd(cmd):
    print(f">>> Running: {cmd}")
    subprocess.run(cmd, shell=True, check=True)

def setup():
    print("--- RENATA LOCAL SETUP HELPER ---")
    
    # 1. Check for .env
    if not os.path.exists(".env"):
        print("Creating .env from .env.example...")
        if os.path.exists(".env.example"):
            with open(".env.example", "r") as f:
                content = f.read()
            with open(".env", "w") as f:
                f.write(content)
            print("!!! PLEASE UPDATE .env WITH YOUR CREDENTIALS !!!")
        else:
            print("Error: .env.example not found. Please create a .env file manually.")
    
    # 2. Setup Venv if missing
    if not os.path.exists("renata"):
        print("Creating virtual environment 'renata'...")
        run_cmd("python -m venv renata")

    # 3. Instructions
    print("\n" + "="*40)
    print("SETUP COMPLETE (OR ALREADY READY)")
    print("="*40)
    print("Next steps:")
    print("1. Activate venv:   .\\renata\\Scripts\\activate")
    print("2. Install deps:    pip install -r requirements.txt")
    print("3. Install browser: playwright install chromium")
    print("\nTo run the bot:")
    print("4. Dashboard:       python main.py")
    print("5. Bot Pilot:       python renata_bot_pilot.py --autopilot")
    print("="*40)

if __name__ == "__main__":
    setup()
