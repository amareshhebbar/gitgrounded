import sys
from pathlib import Path

import uvicorn
from google.adk.cli.fast_api import get_fast_api_app

AGENTS = Path(__file__).resolve().parent / "adk_agents"


def build_app():
    return get_fast_api_app(agents_dir=str(AGENTS), web=False, use_local_storage=False)


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    uvicorn.run(build_app(), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
