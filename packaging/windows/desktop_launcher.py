"""Windows executable entrypoint for Syllabus Auditor.

Run as a foreground localhost server with visible startup logs / first-use token.
Application data is stored outside the installation directory for safe upgrades.
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8765
MODEL_NAME = "Qwen3-1.7B-Q4_K_M.gguf"


def bundled_root() -> Path:
    # PyInstaller --onedir stores resources in _internal. Under a normal Python
    # execution this file lives at <project>/packaging/windows/desktop_launcher.py.
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2])).resolve()


def configure_runtime() -> tuple[Path, Path]:
    root = bundled_root()
    app_data = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "SyllabusAuditor" / "data"
    app_data.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("SA_DATA_DIR", str(app_data))
    os.environ.setdefault("SA_MODEL_PATH", str(root / "models" / MODEL_NAME))
    os.environ["SA_HOST"] = HOST
    os.environ["SA_PORT"] = str(PORT)
    os.environ["SA_SECURE_COOKIES"] = "false"  # localhost; hosted mode uses HTTPS container

    tesseract_dir = root / "tesseract"
    tesseract_exe = tesseract_dir / "tesseract.exe"
    if tesseract_exe.is_file():
        os.environ["PATH"] = str(tesseract_dir) + os.pathsep + os.environ.get("PATH", "")
        if (tesseract_dir / "tessdata").is_dir():
            os.environ["TESSDATA_PREFIX"] = str(tesseract_dir / "tessdata")

    browser_dir = root / "ms-playwright"
    if browser_dir.is_dir():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_dir)
    return root, app_data


def listening() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=0.3):
            return True
    except OSError:
        return False


def open_when_ready() -> None:
    for _ in range(150):
        time.sleep(0.2)
        if listening():
            webbrowser.open(f"http://{HOST}:{PORT}")
            return


def main() -> int:
    root, data_dir = configure_runtime()
    print("Syllabus Auditor - Windows Desktop", flush=True)
    print("Application files:", root, flush=True)
    print("Private data:", data_dir, flush=True)
    print("Open URL:", f"http://{HOST}:{PORT}", flush=True)
    if listening():
        print(f"ERROR: Port {PORT} is already in use. Close the other program first.", file=sys.stderr)
        input("Press Enter to close...")
        return 1

    # Import after setting environment variables; app.config initializes data dirs
    # and the bootstrap token during FastAPI startup.
    from app.main import app
    import uvicorn

    threading.Thread(target=open_when_ready, daemon=True, name="browser-open").start()
    uvicorn.run(app, host=HOST, port=PORT, workers=1, log_level="info", access_log=False)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
    except Exception as exc:
        print("Syllabus Auditor could not start:", exc, file=sys.stderr, flush=True)
        input("Press Enter to close...")
        raise
