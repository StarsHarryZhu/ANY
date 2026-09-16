import json
import questionary

API_KEYS_FILE = "src/api_keys.json"

def load_api_config():
    try:
        with open(API_KEYS_FILE, "r") as f:
            api_config = json.load(f)
    except FileNotFoundError:
        api_config = {}
    return api_config

def to_questionary_type(choices: list, key: str) -> list:
    return [
        {"name": str(item[key]), "value": item} if isinstance(item, dict) else item
        for item in choices
    ]

def select(choices: list, message: str, key: str = "name"):
    return questionary.select(message, choices).ask()






