"""Syllabus Auditor macOS desktop entry point (Cocoa WKWebView via pywebview).

Runs the existing FastAPI application on an ephemeral loopback port in this
process. The installed application never opens its own UI in a browser.
"""
from __future__ import annotations

try:
    import fcntl  # macOS POSIX file locking
except ImportError:
    fcntl = None  # Allow cross-platform import for static tests on Windows
import json
import secrets
import os
import socket
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import IO

TITLE = "Syllabus Auditor"
HOST = "127.0.0.1"
MODEL_FILE = "Qwen3-1.7B-Q4_K_M.gguf"


def bundled_root() -> Path:
    """Path containing copied app/static, models and tesseract assets."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS).resolve()  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[2]


def ensure_import_path() -> None:
    if getattr(sys, "frozen", False):
        return
    root = bundled_root()
    if not (root / "app" / "main.py").is_file():
        raise RuntimeError(f"Syllabus Auditor source is missing: {root / 'app' / 'main.py'}")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def default_data_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / "SyllabusAuditor" / "data"


def data_dir() -> Path:
    return Path(os.environ.get("SA_DATA_DIR") or default_data_dir()).expanduser().resolve()


def configure_runtime(port: int) -> Path:
    root = bundled_root()
    path = data_dir()
    path.mkdir(parents=True, exist_ok=True)
    os.environ["SA_DATA_DIR"] = str(path)
    os.environ["SA_MODEL_PATH"] = str(root / "models" / MODEL_FILE)
    os.environ["SA_DESKTOP_BOOTSTRAP_SECRET"] = secrets.token_urlsafe(48)
    os.environ["SA_HOST"] = HOST
    os.environ["SA_PORT"] = str(port)
    os.environ["SA_SECURE_COOKIES"] = "false"  # Private localhost only

    # For full packages, Tesseract is a bundled executable with its own data.
    ocr_root = root / "tesseract"
    binary = ocr_root / "tesseract"
    if binary.is_file():
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = str(binary)
        os.environ["PATH"] = str(ocr_root) + os.pathsep + os.environ.get("PATH", "")
        tessdata = ocr_root / "tessdata"
        if tessdata.is_dir():
            os.environ["TESSDATA_PREFIX"] = str(tessdata)

    browser_dir = root / "ms-playwright"
    if browser_dir.is_dir():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_dir)
    return path


def select_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def hold_single_instance(path: Path) -> IO[str]:
    """Prevent concurrent writers to the same desktop SQLite database."""
    if fcntl is None:
        raise RuntimeError('macOS desktop lock requires fcntl')
    lock_path = path / "desktop.lock"
    lock = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        lock.close()
        raise RuntimeError("Syllabus Auditor is already running with this data folder") from exc
    return lock


def await_startup(server, worker: threading.Thread, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server.started:
            return
        if not worker.is_alive():
            raise RuntimeError("The local service stopped during startup")
        time.sleep(0.1)
    raise TimeoutError("Syllabus Auditor service did not start")


def _desktop_log(message: str) -> None:
    """Write diagnostics even when native-window callbacks run on a worker."""
    log_file = Path.home() / "Library" / "Logs" / "SyllabusAuditor" / "desktop.log"
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8") as stream:
            stream.write(time.strftime("\n%Y-%m-%d %H:%M:%S ") + message + "\n")
    except OSError:
        pass


def _show_unlock_problem(window, message: str) -> None:
    """Show a useful error in the native window, not a permanent spinner."""
    _desktop_log("Desktop sign-in: " + message)
    message = (
        "Could not open the local desktop workspace. " + message +
        " Close the app and try again. See ~/Library/Logs/SyllabusAuditor/desktop.log."
    )
    script = (
        "(() => { const app = document.getElementById('app'); "
        "if (app) { app.replaceChildren(); const panel=document.createElement('div'); "
        "panel.className='auth-screen'; const card=document.createElement('div'); "
        "card.className='auth-card'; const title=document.createElement('h2'); "
        "title.textContent='Desktop startup problem'; const detail=document.createElement('p'); "
        "detail.textContent=" + json.dumps(message) + "; card.append(title,detail); "
        "panel.append(card); app.append(panel); } })();"
    )
    try:
        window.run_js(script)
    except Exception as exc:
        _desktop_log("Could not display startup error: " + repr(exc))


def _session_created() -> bool:
    """Check that the one-time unlock actually created a backend session.

    The server clears old sessions at startup, so a fresh desktop-local session
    is evidence that the one-time secret was consumed successfully. This is a
    backend check; it does not expose the secret or require JS eval.
    """
    from app.database import one
    return bool(one(
        "SELECT s.token_hash FROM sessions s JOIN users u ON u.id=s.user_id "
        "WHERE u.username=? LIMIT 1", ("desktop-local",)
    ))


def unlock_native_window(window, secret: str, port: int) -> None:
    """Establish an authenticated session without requiring CSP-unsafe eval.

    pywebview.evaluate_js uses JS eval, blocked by our app's Content-Security-
    Policy. run_js dispatches the script directly into WKWebView instead.
    """
    from app.desktop_auth import bootstrap_script, password_required
    if password_required():
        return  # Opt-in startup password: the normal login form is expected.

    try:
        # Avoid injecting while WKWebView still shows a blank initial page.
        if not window.events.loaded.wait(timeout=20):
            _show_unlock_problem(window, "The application page did not finish loading.")
            return
        window.run_js(bootstrap_script(secret, port))
    except Exception as exc:
        _show_unlock_problem(window, "The native sign-in script could not run: " + str(exc))
        return

    # run_js intentionally returns no result. Confirm the protected session
    # appeared rather than assuming that dispatching the JS succeeded.
    for _ in range(50):
        try:
            if _session_created():
                return
        except Exception as exc:
            _desktop_log("Desktop session check: " + repr(exc))
        time.sleep(0.2)
    _show_unlock_problem(window, "Automatic desktop sign-in did not finish.")


def report_failure(exc: BaseException) -> None:
    logfile = Path.home() / "Library" / "Logs" / "SyllabusAuditor" / "desktop.log"
    try:
        logfile.parent.mkdir(parents=True, exist_ok=True)
        with logfile.open("a", encoding="utf-8") as stream:
            stream.write(
                time.strftime("\n%Y-%m-%d %H:%M:%S desktop startup failure\n")
                + "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            )
    except OSError:
        pass
    message = f"Syllabus Auditor could not start.\n\n{exc}\n\nLog: {logfile}"
    try:
        from AppKit import NSAlert
        alert = NSAlert.alloc().init()
        alert.setMessageText_(TITLE)
        alert.setInformativeText_(message)
        alert.runModal()
    except Exception:
        print(message, file=sys.stderr)


def main() -> int:
    if sys.platform != "darwin":
        raise RuntimeError("This desktop launcher is for macOS")
    port = select_port()
    path = configure_runtime(port)
    desktop_secret = os.environ["SA_DESKTOP_BOOTSTRAP_SECRET"]
    lock = hold_single_instance(path)
    server = None
    worker = None
    try:
        ensure_import_path()
        from app.main import app
        import uvicorn
        import webview

        server = uvicorn.Server(uvicorn.Config(
            app=app, host=HOST, port=port, workers=1,
            log_level="warning", access_log=False,
        ))
        worker = threading.Thread(target=server.run, daemon=True, name="syllabus-local-server")
        worker.start()
        await_startup(server, worker)

        webview.settings["ALLOW_DOWNLOADS"] = True
        webview.settings["ALLOW_FILE_URLS"] = False
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        webview.settings["SHOW_DEFAULT_MENUS"] = False
        window = webview.create_window(
            TITLE, f"http://{HOST}:{port}/",
            width=1360, height=860, min_size=(960, 620),
            text_select=True, confirm_close=False,
        )
        webview.start(
            func=lambda: unlock_native_window(window, desktop_secret, port),
            gui="cocoa", debug=False,
        )
        return 0
    finally:
        if server is not None:
            server.should_exit = True
        if worker is not None and worker.is_alive():
            worker.join(timeout=10)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
    except Exception as error:
        report_failure(error)
        raise SystemExit(1)
