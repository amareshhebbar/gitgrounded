import argparse
import os
import sys

from gitgrounded import __version__

PYPI_URL = "https://pypi.org/pypi/gitgrounded/json"
REPO_URL = "https://github.com/amareshhebbar/gitgrounded"


def latest_release(timeout: float = 3.0) -> str | None:
    if os.environ.get("GITGROUNDED_OFFLINE", "").strip().lower() in ("1", "true", "yes"):
        return None
    if os.environ.get("GITGROUNDED_NO_UPDATE_CHECK"):
        return None
    try:
        import requests

        resp = requests.get(PYPI_URL, timeout=timeout)
        resp.raise_for_status()
        return str(resp.json()["info"]["version"])
    except Exception:
        return None


def is_newer(latest: str, current: str) -> bool:
    try:
        from packaging.version import Version

        return Version(latest) > Version(current)
    except Exception:
        return False


def render(current: str, latest: str | None) -> str:
    lines = [f"gitgrounded {current}"]
    if latest is None:
        lines.append("latest: could not reach PyPI, skipped update check")
    elif is_newer(latest, current):
        lines.append(f"latest: {latest} is available")
        lines.append("update: pip install --upgrade gitgrounded")
    else:
        lines.append(f"latest: {latest}, you are up to date")
    lines.append(f"Missing a feature? Add it yourself: {REPO_URL}")
    return "\n".join(lines)


class VersionAction(argparse.Action):
    def __init__(self, option_strings, dest=argparse.SUPPRESS, default=argparse.SUPPRESS, help=None):
        super().__init__(option_strings, dest=dest, default=default, nargs=0, help=help)

    def __call__(self, parser, namespace, values, option_string=None):
        sys.stdout.write(render(__version__, latest_release()) + "\n")
        parser.exit(0)
