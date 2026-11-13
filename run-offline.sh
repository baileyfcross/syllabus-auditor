#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then echo 'First run: python tools/install_offline.py';exit 1;fi
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
