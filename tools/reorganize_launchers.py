"""One-time, idempotent repository cleanup for Syllabus Auditor launchers.

Run from any directory with: py -3.14 tools\\reorganize_launchers.py
The script only moves known legacy launchers; desktop and installer entrypoints stay in root.
"""
from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOVES = {
    "start-local.ps1": "scripts/windows/start-local.ps1",
    "Start Syllabus Auditor.bat": "scripts/windows/Start Syllabus Auditor.bat",
    "run-offline.bat": "scripts/windows/run-offline.bat",
    "start-local.sh": "scripts/unix/start-local.sh",
    "run-offline.sh": "scripts/unix/run-offline.sh",
    "Run Syllabus Auditor.command": "scripts/unix/Run Syllabus Auditor.command",
}


def replace_required(content: str, before: str, after: str, label: str) -> str:
    if after in content:
        return content
    if before not in content:
        raise RuntimeError(f"Unexpected content in {label}: expected {before!r}. No changes applied to that file.")
    return content.replace(before, after)


def patched(rel_path: str, content: str) -> str:
    if rel_path == "scripts/windows/start-local.ps1":
        content = replace_required(content,
            "Set-Location -LiteralPath $PSScriptRoot",
            "$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\\..')).Path\nSet-Location -LiteralPath $ProjectRoot",
            rel_path)
        for old, new in [
            ("Join-Path $PSScriptRoot '.venv", "Join-Path $ProjectRoot '.venv"),
            ("Join-Path $PSScriptRoot 'models", "Join-Path $ProjectRoot 'models"),
            ("Join-Path $PSScriptRoot 'tools", "Join-Path $ProjectRoot 'tools"),
        ]:
            content = replace_required(content, old, new, rel_path)
    if rel_path == "scripts/windows/Start Syllabus Auditor.bat":
        content = replace_required(content, 'cd /d "%~dp0"', 'cd /d "%~dp0..\\.."', rel_path)
    if rel_path == "scripts/windows/run-offline.bat":
        content = replace_required(content, 'cd /d "%~dp0"', 'cd /d "%~dp0..\\.."', rel_path)
    if rel_path in ("scripts/unix/start-local.sh", "scripts/unix/run-offline.sh"):
        content = replace_required(content, 'cd "$(dirname "$0")"', 'cd "$(dirname "$0")/../.."', rel_path)
    return content


def updated_readme(content: str) -> str:
    changes = [
        (".\\start-local.ps1", ".\\scripts\\windows\\start-local.ps1"),
        ("./start-local.sh", "./scripts/unix/start-local.sh"),
        ("`./run-offline.sh`", "`./scripts/unix/run-offline.sh`"),
        ("`run-offline.bat`", "`scripts\\windows\\run-offline.bat`"),
    ]
    for old, new in changes:
        content = content.replace(old, new)
    return content


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Show planned changes, without writing")
    args = parser.parse_args()
    if not (ROOT / "app" / "main.py").is_file():
        raise SystemExit("Cannot locate app/main.py. Extract this patch into the Syllabus Auditor root first.")
    if not (ROOT / "packaging" / "windows" / "build-windows.ps1").is_file():
        raise SystemExit("Missing packaging/windows/build-windows.ps1. Refusing to reorganize an incomplete project.")
    existing = []
    for source, dest in MOVES.items():
        source_path, dest_path = ROOT / source, ROOT / dest
        if source_path.exists() and dest_path.exists():
            raise SystemExit(f"Both {source} and {dest} exist. Resolve manually to avoid overwriting edits.")
        if not source_path.exists() and not dest_path.exists():
            raise SystemExit(f"Missing {source}; expected either root version or {dest}.")
        existing.append((source_path if source_path.exists() else dest_path, dest_path, source_path.exists()))
    contents = {}
    for old_path, dest_path, needs_move in existing:
        text = old_path.read_text(encoding="utf-8-sig")
        contents[dest_path] = patched(dest_path.relative_to(ROOT).as_posix(), text)
    readme = ROOT / "README.md"
    new_readme = updated_readme(readme.read_text(encoding="utf-8")) if readme.exists() else None
    print("Keeping root launchers: Build Windows Installer.bat, Start Syllabus Auditor Desktop.bat")
    for original, destination, should_move in existing:
        print(("MOVE  " if should_move else "CHECK ") + str(original.relative_to(ROOT)) + " -> " + str(destination.relative_to(ROOT)))
    if new_readme is not None:
        print("UPDATE README.md references")
    if args.dry_run:
        print("Dry run: no files changed.")
        return
    backup = ROOT / "data" / "launcher-cleanup-backup" / datetime.now().strftime("%Y%m%d-%H%M%S")
    for original, destination, should_move in existing:
        (backup / original.relative_to(ROOT)).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, backup / original.relative_to(ROOT))
    if readme.exists():
        (backup / "README.md").parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(readme, backup / "README.md")
    for original, destination, should_move in existing:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if should_move:
            original.rename(destination)
        destination.write_text(contents[destination], encoding="utf-8", newline="\n")
    if new_readme is not None:
        readme.write_text(new_readme, encoding="utf-8", newline="\n")
    print("Complete. Original files backed up under", backup.relative_to(ROOT))
    print('Run "git add -A" and "git status" to review Git renames before committing.')


if __name__ == "__main__":
    main()
