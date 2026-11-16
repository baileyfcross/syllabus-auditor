"""Opt-in native desktop authentication, isolated from the hosted web app.

Only a desktop launcher can enable this mode by setting a fresh, random secret
before app.main is imported. The server remains on IPv4 loopback and *all*
regular API endpoints retain their session/CSRF authorization requirements.
"""
from __future__ import annotations

import hmac
import json
import os
import threading
from pathlib import Path

from .config import DATA_DIR, HOST

DESKTOP_USER = "desktop-local"
PREFS_FILE = DATA_DIR / "desktop-preferences.json"
_bootstrap_secret = os.environ.pop("SA_DESKTOP_BOOTSTRAP_SECRET", "")
ENABLED = HOST == "127.0.0.1" and len(_bootstrap_secret) >= 48
_lock = threading.Lock()
_used = False


def password_required() -> bool:
    """A corrupt lock file fails closed rather than unexpectedly unlocking."""
    if not ENABLED:
        return True
    if not PREFS_FILE.is_file():
        return False
    try:
        config = json.loads(PREFS_FILE.read_text(encoding="utf-8"))
        if type(config.get("require_password")) is not bool:
            raise ValueError("Invalid desktop preference")
        return config["require_password"]
    except (OSError, ValueError, AttributeError) as exc:
        raise RuntimeError("Desktop lock preferences cannot be read. Restore a valid desktop-preferences.json file.") from exc


def set_password_required(value: bool) -> None:
    if not ENABLED or type(value) is not bool:
        raise ValueError("Desktop lock is only configurable from the native desktop app")
    PREFS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = PREFS_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps({"require_password": value}, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    os.replace(temp, PREFS_FILE)


def consume_secret(secret: str) -> bool:
    """Permit exactly one local native-WebView login per desktop process."""
    global _used
    if not ENABLED or password_required():
        return False
    with _lock:
        if _used or not hmac.compare_digest(secret, _bootstrap_secret):
            return False
        _used = True
        return True


def bootstrap_script(secret: str, port: int) -> str:
    """Send one native-only secret via a request header, never a query string.

    The secret remains inside a short-lived JS closure, and the page reloads
    after an HttpOnly cookie has been established. The script never touches
    any external origin, including if the WebView navigates away.
    """
    origin = f"http://127.0.0.1:{port}"
    return (
        "(() => {"
        f"if (location.origin !== {json.dumps(origin)}) return false;"
        "if (!document.getElementById('app')) return false;"
        "if (window.__saDesktopUnlockStarted) return true;"
        "window.__saDesktopUnlockStarted = true;"
        "fetch('/api/desktop/unlock', {method:'POST', credentials:'same-origin', "
        "headers:{'X-SA-Desktop-Secret':" + json.dumps(secret) + "}})"
        ".then(r => { if (!r.ok) throw Error('Desktop session was not authorized'); return r.json(); })"
        ".then(() => location.replace('/'))"
        ".catch(err => { document.getElementById('app').textContent = "
        "'Syllabus Auditor could not unlock the local desktop session: ' + err.message; });"
        "return true; })()"
    )
