"""Source-mode Syllabus Auditor desktop launcher with automatic Tailwind build.

Node.js is a *development-only* dependency. Production PyInstaller builds include
app/static/tailwind.generated.css and do not execute npm at application startup.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS_SOURCE = ROOT / 'styles' / 'tailwind.css'
MANIFEST = ROOT / 'package.json'
CSS_OUTPUT = ROOT / 'app' / 'static' / 'tailwind.generated.css'


def npm_command() -> str:
    result = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
    if not result:
        raise RuntimeError('Tailwind requires Node.js/npm on the development machine. Install Node.js LTS and reopen the terminal.')
    return result


def build_css(npm: str | None = None) -> str | None:
    if not CSS_SOURCE.is_file() and not MANIFEST.is_file():
        print('[CSS] Tailwind is not installed; using the existing CSS.', flush=True)
        return None
    if not CSS_SOURCE.is_file() or not MANIFEST.is_file():
        raise RuntimeError('Incomplete Tailwind installation: both package.json and styles/tailwind.css must exist.')
    npm = npm or npm_command()
    if not (ROOT / 'node_modules' / '.bin').is_dir():
        command = 'ci' if (ROOT / 'package-lock.json').is_file() else 'install'
        print('[CSS] Installing Tailwind development tools...', flush=True)
        subprocess.run([npm, command, '--no-audit', '--no-fund'], cwd=ROOT, check=True)
    try:
        scripts = json.loads(MANIFEST.read_text(encoding='utf-8')).get('scripts', {})
    except (ValueError, OSError) as exc:
        raise RuntimeError('Cannot read Tailwind package.json') from exc
    build_script = 'build' if scripts.get('build') else 'build:css' if scripts.get('build:css') else None
    if not build_script:
        raise RuntimeError('Tailwind package.json is missing the build/build:css npm script.')
    print(f'[CSS] Compiling Tailwind (npm run {build_script})...', flush=True)
    subprocess.run([npm, 'run', build_script], cwd=ROOT, check=True)
    if not CSS_OUTPUT.is_file() or CSS_OUTPUT.stat().st_size < 100:
        raise RuntimeError('Tailwind build did not produce a nonempty app/static/tailwind.generated.css.')
    print('[CSS] Tailwind compilation complete.', flush=True)
    return npm


def terminate_watcher(proc: subprocess.Popen | None) -> None:
    if not proc or proc.poll() is not None:
        return
    if os.name == 'nt':
        # npm.cmd starts a separate node.exe child. Shut down that entire tree.
        subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Start the Syllabus Auditor native Windows development window')
    parser.add_argument('--watch', action='store_true', help='Recompile Tailwind automatically while the window is open')
    args = parser.parse_args(argv)
    if os.name != 'nt':
        raise RuntimeError('This launcher starts the Windows desktop window. Use the macOS preview script on macOS.')
    desktop = ROOT / 'packaging' / 'windows' / 'desktop_launcher.py'
    if not desktop.is_file():
        raise RuntimeError('Missing packaging/windows/desktop_launcher.py')
    npm = build_css()
    watcher = None
    try:
        if args.watch and npm:
            scripts = json.loads(MANIFEST.read_text(encoding='utf-8')).get('scripts', {})
            if not scripts.get('watch:css'):
                raise RuntimeError('The --watch option requires the watch:css script in package.json.')
            print('[CSS] Watching Tailwind sources until the desktop window closes...', flush=True)
            watcher = subprocess.Popen([npm, 'run', 'watch:css'], cwd=ROOT,
                                       creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        elif args.watch:
            print('[CSS] Watch mode skipped: Tailwind is not installed.', flush=True)
        env = os.environ.copy()
        env['SA_DATA_DIR'] = str(ROOT / 'data')
        return subprocess.run([sys.executable, str(desktop)], cwd=ROOT, env=env,
                              check=False).returncode
    finally:
        terminate_watcher(watcher)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f'Could not start Syllabus Auditor desktop: {exc}', file=sys.stderr)
        raise SystemExit(1)
