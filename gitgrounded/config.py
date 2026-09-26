import os
import yaml
from dotenv import load_dotenv

load_dotenv()


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def get_mode():
    return os.environ.get("GITGROUNDED_MODE", "dev")