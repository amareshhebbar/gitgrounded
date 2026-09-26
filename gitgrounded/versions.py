import os
import json
import re
import shutil


def safe_label(label):
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", label.strip())


def latest_version(version_dir):
    if not os.path.isdir(version_dir):
        return None
    nums = []
    for name in os.listdir(version_dir):
        m = re.match(r"^v(\d+)\.json$", name)
        if m:
            nums.append(int(m.group(1)))
    return max(nums) if nums else None


def save_version(version_dir, data):
    os.makedirs(version_dir, exist_ok=True)
    n = (latest_version(version_dir) or 0) + 1
    path = os.path.join(version_dir, f"v{n}.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return n


def load_version(version_dir, n):
    path = os.path.join(version_dir, f"v{n}.json")
    with open(path) as f:
        return json.load(f)


def delete_label(version_dir):
    if not os.path.isdir(version_dir):
        return 0
    count = latest_version(version_dir) or 0
    shutil.rmtree(version_dir)
    return count


def delete_version(version_dir, n):
    path = os.path.join(version_dir, f"v{n}.json")
    if not os.path.exists(path):
        return False
    os.remove(path)
    return True


def list_labels(versions_root):
    if not os.path.isdir(versions_root):
        return []
    entries = []
    for name in sorted(os.listdir(versions_root)):
        version_dir = os.path.join(versions_root, name)
        if os.path.isdir(version_dir):
            entries.append((name, latest_version(version_dir) or 0))
    return entries


def delete_all(versions_root):
    if not os.path.isdir(versions_root):
        return 0
    count = len([n for n in os.listdir(versions_root) if os.path.isdir(os.path.join(versions_root, n))])
    shutil.rmtree(versions_root)
    return count