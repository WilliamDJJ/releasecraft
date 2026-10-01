"""Small user-local desktop preferences, separate from projects and public payloads."""
import json
from .directory import Directory
from .managed import state_directory
from .safety import ReleaseError, atomic_json, read_safe


def language(state=None):
    try:
        value=json.loads(read_safe(state or state_directory(), "desktop-preferences.json", 1024)[0])
        return value["language"] if value.get("schema")==1 and value.get("language") in ("en","zh") else "en"
    except (OSError,ReleaseError,ValueError,TypeError,AttributeError):
        return "en"


def save_language(value, state=None):
    if value not in ("en","zh"):
        raise ValueError("Unsupported interface language")
    with Directory(state or state_directory(),create=True) as directory:
        atomic_json(directory.path/"desktop-preferences.json", {"schema":1,"language":value})
