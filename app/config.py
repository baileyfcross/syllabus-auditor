import os
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv('SA_DATA_DIR', str(ROOT/'data'))).resolve()
MODEL_PATH = Path(os.getenv('SA_MODEL_PATH', str(ROOT/'models'/'Qwen3-1.7B-Q4_K_M.gguf')))
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR = DATA_DIR/'uploads'
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR/'syllabus_auditor.sqlite3'
MAX_UPLOAD = int(os.getenv('SA_MAX_UPLOAD_MB', '25'))*1024*1024
HOST = os.getenv('SA_HOST','127.0.0.1')
PORT = int(os.getenv('SA_PORT','8765'))
SECURE_COOKIES = os.getenv('SA_SECURE_COOKIES','false').lower() == 'true'
PUBLIC_BASE_URL = os.getenv('SA_PUBLIC_BASE_URL','').rstrip('/')
SESSION_DAYS = 7
AI_THREADS = int(os.getenv('SA_AI_THREADS','4'))
AI_CONTEXT = int(os.getenv('SA_AI_CONTEXT','3072'))
MONITOR_INTERVAL_HOURS = max(1, int(os.getenv('SA_MONITOR_INTERVAL_HOURS','24')))
