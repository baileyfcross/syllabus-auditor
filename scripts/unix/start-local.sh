#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
if [ ! -f models/Qwen3-1.7B-Q4_K_M.gguf ]; then
  echo 'Bundled AI model is absent in this source distribution; deterministic validation remains available.'
  echo 'To build a complete offline distribution, see README.md.'
fi
if [ ! -d .venv ]; then python3 -m venv .venv; fi
source .venv/bin/activate
python -m pip install -r requirements.txt
if [ -f models/Qwen3-1.7B-Q4_K_M.gguf ]; then
  if ! python -c 'import llama_cpp' 2>/dev/null; then
    python -m pip install 'llama-cpp-python>=0.3.5,<1' || echo 'Embedded model runtime installation failed; rule checks remain available.'
  fi
fi
exec python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
