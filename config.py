"""
Configuration file for RENA Bot
Stores user preferences and settings
"""
import json
import os

CONFIG_FILE = "rena_config.json"

# Default configuration
DEFAULT_CONFIG = {
    "auto_join_enabled": False,
    "auto_join_delay_seconds": 30,
    "bot_name": "Rena AI | Meeting Assistant",
    "send_email_summaries": False,
    "send_chat_intro": True,
    "record_audio": True,
    "email_recipients": "all_participants"  # or "organizer_only"
}

def load_config():
    """Load configuration from file or create default"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                # Merge with defaults in case new settings were added
                return {**DEFAULT_CONFIG, **config}
        except:
            return DEFAULT_CONFIG.copy()
    return DEFAULT_CONFIG.copy()

def save_config(config):
    """Save configuration to file"""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

def get_setting(key, default=None):
    """Get a specific setting"""
    config = load_config()
    return config.get(key, default)

def update_setting(key, value):
    """Update a specific setting"""
    config = load_config()
    config[key] = value
    save_config(config)
    return config
