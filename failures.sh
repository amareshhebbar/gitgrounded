#!/usr/bin/env bash
set -u
cd "$(dirname "$0")"
PY=.venv/bin/python
[ -x "$PY" ] || PY=python3
exec "$PY" failures.py "$@"
