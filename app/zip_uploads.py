"""Bounded, in-memory import of ZIP batches of syllabus documents.

Only validated PDF/DOCX/TXT bytes are handed to the existing audit pipeline.
Archive paths are never used for filesystem extraction.
"""
from __future__ import annotations

import io
import re
import stat
import zipfile
from pathlib import Path

from .config import MAX_UPLOAD

MAX_BATCH_DOCUMENTS = 100
MAX_BATCH_BYTES = 200 * 1024 * 1024
MAX_ZIP_UPLOAD_BYTES = MAX_BATCH_BYTES
MAX_ZIP_ENTRIES = 1500
MAX_COMPRESSION_RATIO = 1000
DOCUMENT_EXTENSIONS = {'.pdf', '.docx', '.txt'}


def _parts(member: str) -> list[str]:
    # ZIP stores POSIX-style paths, but reject Windows-form traversal as well.
    normalized = member.replace('\\', '/')
    if not normalized or normalized.startswith('/') or re.match(r'^[a-zA-Z]:', normalized):
        raise ValueError(f'Unsafe ZIP entry path: {member[:120]}')
    parts = normalized.rstrip('/').split('/')
    if len(parts) > 20 or any(p in ('', '.', '..') or ':' in p for p in parts):
        raise ValueError(f'Unsafe ZIP entry path: {member[:120]}')
    return parts


def _display_name(parts: list[str]) -> str:
    # Preserve folder context for e.g. one syllabus.docx per student folder,
    # while avoiding filesystem separators or control characters in filenames.
    flat = ' - '.join(parts)
    flat = re.sub(r'[\x00-\x1f\x7f<>:"/\\|?*]', '_', flat).strip(' .')
    suffix = Path(parts[-1]).suffix.lower()
    base = flat[:-len(suffix)] if suffix else flat
    return (base[:max(1, 180 - len(suffix))].rstrip(' .') or 'syllabus') + suffix


def _unique_name(name: str, used: set[str]) -> str:
    if name.casefold() not in used:
        used.add(name.casefold())
        return name
    suffix = Path(name).suffix
    stem = name[:-len(suffix)] if suffix else name
    i = 2
    while True:
        candidate = f'{stem[:max(1, 180 - len(suffix) - len(str(i)) - 3)]} ({i}){suffix}'
        if candidate.casefold() not in used:
            used.add(candidate.casefold())
            return candidate
        i += 1


def expand_syllabus_uploads(uploads: list[tuple[str, bytes]], validate_upload):
    """Return (staged documents, skipped_count, skipped_preview).

    Raises ValueError for invalid archives, unsafe members, size breaches,
    corrupt supported documents, or entirely empty/unsupported archives.
    Staged tuples match the existing (filename, extension, bytes) interface.
    """
    staged: list[tuple[str, str, bytes]] = []
    used: set[str] = set()
    skipped_count = 0
    skipped_preview: list[str] = []
    total_bytes = 0

    def stage(filename: str, content: bytes, source: str):
        nonlocal total_bytes
        if len(staged) >= MAX_BATCH_DOCUMENTS:
            raise ValueError(f'A batch can contain at most {MAX_BATCH_DOCUMENTS} syllabi (including documents inside ZIP files)')
        if len(content) > MAX_UPLOAD:
            raise ValueError(f'{source}: document exceeds the {MAX_UPLOAD // 1024 // 1024} MB limit')
        total_bytes += len(content)
        if total_bytes > MAX_BATCH_BYTES:
            raise ValueError('Combined expanded syllabus data exceeds 200 MB')
        try:
            suffix = validate_upload(filename, content)
        except ValueError as exc:
            raise ValueError(f'{source}: {exc}') from exc
        staged.append((_unique_name(filename, used), suffix, content))

    for upload_name, content in uploads:
        if not upload_name:
            raise ValueError('Upload filename is missing')
        ext = Path(upload_name).suffix.lower()
        if ext != '.zip':
            stage(_display_name([Path(upload_name.replace('\\', '/')).name]), content, upload_name)
            continue
        if not content or len(content) > MAX_ZIP_UPLOAD_BYTES:
            raise ValueError('ZIP archive is empty or exceeds the 200 MB compressed size limit')
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                members = archive.infolist()
                if len(members) > MAX_ZIP_ENTRIES:
                    raise ValueError(f'{upload_name}: ZIP contains too many entries (maximum {MAX_ZIP_ENTRIES})')
                # Check declared aggregate sizes before decompressing anything.
                declared_total = sum(m.file_size for m in members if not m.is_dir() and Path(m.filename).suffix.lower() in DOCUMENT_EXTENSIONS)
                if declared_total > MAX_BATCH_BYTES:
                    raise ValueError(f'{upload_name}: ZIP expands beyond the 200 MB batch limit')
                for member in members:
                    parts = _parts(member.filename)
                    unix_type = stat.S_IFMT(member.external_attr >> 16) if member.create_system == 3 else 0
                    if unix_type not in (0, stat.S_IFDIR, stat.S_IFREG):
                        raise ValueError(f'{upload_name}: ZIP contains a symbolic link or special file: {member.filename[:120]}')
                    if member.flag_bits & 1:
                        raise ValueError(f'{upload_name}: password-protected ZIP entries are not supported')
                    if member.is_dir():
                        continue
                    # Non-syllabus entries are ignored without decompressing them.
                    # Common OS-generated metadata must not count against size limits.
                    if any(p == '__MACOSX' for p in parts) or parts[-1] in ('.DS_Store', 'Thumbs.db'):
                        skipped_count += 1
                        continue
                    suffix = Path(parts[-1]).suffix.lower()
                    if suffix not in DOCUMENT_EXTENSIONS:
                        skipped_count += 1
                        if len(skipped_preview) < 12:
                            skipped_preview.append(f'{upload_name}: {member.filename} (unsupported file type)')
                        continue
                    if member.file_size > MAX_UPLOAD:
                        raise ValueError(f'{upload_name}: {member.filename[:120]} exceeds the per-document size limit')
                    if member.file_size > MAX_COMPRESSION_RATIO * max(member.compress_size, 1) and member.file_size > 1024 * 1024:
                        raise ValueError(f'{upload_name}: suspicious ZIP compression ratio for {member.filename[:120]}')
                    # Bounded decompression: never extract archive paths to disk.
                    with archive.open(member, 'r') as stream:
                        data = stream.read(MAX_UPLOAD + 1)
                    if len(data) != member.file_size:
                        raise ValueError(f'{upload_name}: invalid expanded size for {member.filename[:120]}')
                    stage(_display_name(parts), data, f'{upload_name} / {member.filename}')
        except (zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError, NotImplementedError, EOFError, OSError) as exc:
            raise ValueError(f'{upload_name}: invalid, encrypted, damaged or unsupported ZIP archive: {exc}') from exc
    if not staged:
        raise ValueError('No supported syllabus documents found. Add PDF, DOCX, or UTF-8 TXT files to the ZIP')
    return staged, skipped_count, skipped_preview
