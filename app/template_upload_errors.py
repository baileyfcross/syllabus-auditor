"""Private diagnostics for failures while importing master syllabus templates.

Logs contain exception traces, but are never returned over the HTTP API.
This module is intentionally dependency-free and safe for PyInstaller.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os
import secrets
import traceback

from .config import DATA_DIR

LOG_PATH = DATA_DIR / 'logs' / 'template-uploads.log'


def record_template_upload_error(exc: Exception, stage: str, filename: str = '') -> str:
    """Record an unexpected error and return an opaque reference for the UI.

    The original filename and traceback are only written to the user's private
    local data directory, never exposed through the web/API response.
    """
    ref = secrets.token_hex(6)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open('a', encoding='utf-8') as log:
            log.write(f'\n[{datetime.now(timezone.utc).isoformat()}] '
                      f'master-template-upload ref={ref} stage={stage} '
                      f'filename={Path(filename or "(unnamed)").name!r}\n')
            traceback.print_exception(type(exc), exc, exc.__traceback__, file=log)
        try:
            os.chmod(LOG_PATH, 0o600)
        except OSError:
            pass
    except Exception:
        # Never turn a template parsing/storage exception into a logging failure.
        pass
    return ref
