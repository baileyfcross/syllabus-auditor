"""Syllabus Auditor Windows desktop entry point.

Runs the existing FastAPI backend *inside this process* on a random loopback port
and presents the local application in a native Windows WebView2 window. Nothing
is opened in the user's default browser. The hosted web app is unchanged.
"""
from __future__ import annotations

import ctypes
import json
import secrets
import os
import socket
import sys
import threading
import time
import traceback
from pathlib import Path

HOST = "127.0.0.1"
MODEL_NAME = "Qwen3-1.7B-Q4_K_M.gguf"
TITLE = "Syllabus Auditor"


def bundled_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2])).resolve()


def ensure_app_import_path() -> Path:
    """Make the source package importable when this file runs as a script.

    `python packaging/windows/desktop_launcher.py` puts packaging/windows on
    sys.path, *not* the project root. Frozen PyInstaller builds use its embedded
    module importer, so we leave its import path alone.
    """
    if getattr(sys, "frozen", False):
        return bundled_root()
    root = Path(__file__).resolve().parents[2]
    if not (root / "app" / "__init__.py").is_file() or not (root / "app" / "main.py").is_file():
        raise RuntimeError(
            "Could not find the Syllabus Auditor app package next to the "
            "desktop launcher. Install this patch in the project root."
        )
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


def user_data_dir() -> Path:
    return Path(os.environ.get("SA_DATA_DIR") or (Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "SyllabusAuditor" / "data")).resolve()


def configure_runtime(port: int) -> tuple[Path, Path]:
    root = bundled_root()
    data_dir = user_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["SA_DATA_DIR"] = str(data_dir)
    os.environ.setdefault("SA_MODEL_PATH", str(root / "models" / MODEL_NAME))
    os.environ["SA_DESKTOP_BOOTSTRAP_SECRET"] = secrets.token_urlsafe(48)
    os.environ["SA_HOST"] = HOST
    os.environ["SA_PORT"] = str(port)
    os.environ["SA_SECURE_COOKIES"] = "false"  # Only loopback; hosted mode keeps HTTPS.

    ocr = root / "tesseract"
    if (ocr / "tesseract.exe").is_file():
        os.environ["PATH"] = str(ocr) + os.pathsep + os.environ.get("PATH", "")
        if (ocr / "tessdata").is_dir():
            os.environ["TESSDATA_PREFIX"] = str(ocr / "tessdata")

    browser_dir = root / "ms-playwright"
    if browser_dir.is_dir():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_dir)
    return root, data_dir


def select_port() -> int:
    # Avoid conflicts with a developer's localhost:8765 web server and other apps.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def error_message(message: str) -> None:
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, message, TITLE, 0x10)
    else:
        print(message, file=sys.stderr)


def report_failure(exc: BaseException) -> None:
    log = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "SyllabusAuditor" / "logs" / "desktop.log"
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as f:
            f.write(time.strftime("\n%Y-%m-%d %H:%M:%S desktop startup failure\n"))
            f.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    except OSError:
        pass
    error_message(f"Syllabus Auditor could not start.\n\n{exc}\n\nDetails: {log}")


def singleton_mutex():
    """Prevent two installed desktop processes from auditing the same database."""
    if sys.platform != "win32":
        return None
    kernel = ctypes.windll.kernel32
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel.CreateMutexW(None, False, "Local\\SyllabusAuditorDesktop")
    if not handle:
        raise OSError("Could not create desktop application mutex")
    if kernel.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        kernel.CloseHandle(ctypes.c_void_p(handle))
        error_message("Syllabus Auditor is already running.\nSwitch to its existing application window.")
        return False
    return handle


def await_server(server, thread: threading.Thread, port: int, timeout: float = 30) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if server.started:
            return
        if not thread.is_alive():
            raise RuntimeError("The local application service stopped before initialization.")
        time.sleep(0.1)
    raise TimeoutError(f"Application service did not start on port {port}.")


def unlock_native_window(window, secret: str, port: int) -> None:
    """Open a secure desktop-only session without revealing a password or URL token."""
    from app.desktop_auth import bootstrap_script, password_required
    if password_required():
        return  # Explicit startup lock: display the normal password form.
    script = bootstrap_script(secret, port)
    for _ in range(50):
        try:
            if window.evaluate_js(script):
                return
        except Exception:
            pass
        time.sleep(0.15)
    raise RuntimeError('Desktop session could not be initialized in the application window')


def main() -> int:
    mutex = singleton_mutex()
    if mutex is False:
        return 0
    server = None
    thread = None
    try:
        port = select_port()
        _, data_dir = configure_runtime(port)
        desktop_secret = os.environ["SA_DESKTOP_BOOTSTRAP_SECRET"]
        # Source launches need the project root on sys.path; frozen builds use
        # PyInstaller's embedded modules. Configure data paths before app import.
        ensure_app_import_path()
        from app.main import app
        import uvicorn
        import webview

        server = uvicorn.Server(uvicorn.Config(app=app, host=HOST, port=port,
                                              workers=1, log_level="warning", access_log=False))
        thread = threading.Thread(target=server.run, name="syllabus-local-server", daemon=True)
        thread.start()
        await_server(server, thread, port)

        webview.settings["ALLOW_DOWNLOADS"] = True
        webview.settings["ALLOW_FILE_URLS"] = False
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        webview.settings["SHOW_DEFAULT_MENUS"] = False
        window = webview.create_window(TITLE, f"http://{HOST}:{port}/",
                                       width=1360, height=860, min_size=(960, 620),
                                       text_select=True, confirm_close=False)
        # The WebView uses the OS-provided Edge WebView2 engine; no extra browser window.
        webview.start(func=lambda: unlock_native_window(window, desktop_secret, port),
                      gui="edgechromium", debug=False)
        return 0
    finally:
        if server:
            server.should_exit = True
        if thread and thread.is_alive():
            thread.join(timeout=10)
        if mutex and sys.platform == "win32":
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(mutex))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
    except Exception as exc:
        report_failure(exc)
        raise SystemExit(1)
