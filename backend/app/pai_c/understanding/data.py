"""Load policy at use time so data changes take effect without code edits."""
import json
from pathlib import Path

DATA_DIR = Path(__file__).parent


def load_policy():
    return json.loads((DATA_DIR / "policy.json").read_text(encoding="utf-8"))


def load_areas(directory=None):
    """The coverage areas; keys starting with "_" are notes, not areas."""
    data = json.loads(((directory or DATA_DIR) / "areas.json").read_text(encoding="utf-8"))
    return {key: spec for key, spec in data.items() if not key.startswith("_")}


def at_path(data, path):
    for key in path.split("."):
        data = data.get(key, {})
    return data


def set_path(data, path, value):
    keys = path.split(".")
    for key in keys[:-1]:
        data = data.setdefault(key, {})
    data[keys[-1]] = value
