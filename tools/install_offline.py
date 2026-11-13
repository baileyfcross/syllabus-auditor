"""Install all Python dependencies from prepackaged wheels (no network)."""
import subprocess,sys,venv,os
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
WHEELS=ROOT/'vendor'/'wheels'
if not WHEELS.is_dir():raise SystemExit('Offline wheels not bundled: use build_distribution.py --complete on a matching OS and Python version')
if not (ROOT/'models'/'Qwen3-1.7B-Q4_K_M.gguf').is_file():raise SystemExit('Bundled GGUF model missing')
venv.create(ROOT/'.venv',with_pip=True)
python=ROOT/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
subprocess.check_call([str(python),'-m','pip','install','--no-index','--find-links',str(WHEELS),'-r',str(ROOT/'requirements-ai.txt')])
print('Offline runtime installed. Launch with:',python,'-m uvicorn app.main:app --host 127.0.0.1 --port 8765')
