import json
from pathlib import Path

def save_json(content,file_path:Path):
    with open(file_path, 'w') as f:
        json.dump(content, f, indent=4)