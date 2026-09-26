import os
import json
import hashlib

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".cache")


def _key(*parts):
    joined = "||".join(str(p) for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _path(namespace, key):
    ns_dir = os.path.join(CACHE_DIR, namespace)
    os.makedirs(ns_dir, exist_ok=True)
    return os.path.join(ns_dir, f"{key}.json")


def get(namespace, *parts):
    key = _key(*parts)
    path = _path(namespace, key)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def set(namespace, value, *parts):
    key = _key(*parts)
    path = _path(namespace, key)
    with open(path, "w") as f:
        json.dump(value, f, indent=2)
    return value
