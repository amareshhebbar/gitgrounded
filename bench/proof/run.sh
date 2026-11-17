#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
[ -f .env ] && set -a && . ./.env && set +a
[ -f ../../.env ] && set -a && . ../../.env && set +a

MAX_ARG=""
[ "${SMOKE:-0}" = "1" ] && MAX_ARG="--max 1"
[ -n "${MAX:-}" ] && MAX_ARG="--max $MAX"

python build_repo.py work/triage-bench
python run.py --repo work/triage-bench $MAX_ARG
python report.py
python verify.py
echo "done. publish with: python $HERE/publish.py"
