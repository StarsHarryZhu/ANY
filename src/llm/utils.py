import json

API_KEYS_FILE = "src/api_keys.json"

def load_api_keys():
    try:
        with open(API_KEYS_FILE, "r") as f:
            api_keys = json.load(f)
    except FileNotFoundError:
        api_keys = {}
    return api_keys






