"""Source-level guards for build-time Tailwind integration."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def test_npm_build_alias():
    manifest = json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))
    assert manifest['scripts']['build'] == 'npm run build:css'
    assert 'tailwindcss' in manifest['scripts']['build:css']


def test_windows_compiles_before_pyinstaller():
    source = (ROOT / 'packaging/windows/build-windows.ps1').read_text(encoding='utf-8')
    assert 'npm.cmd' in source
    assert "@('run','build')" in source
    assert 'Build-FrontendCss' in source
    assert source.index('Build-FrontendCss\n') < source.index("'-m','PyInstaller'")
    assert "@('ci','--no-audit','--no-fund')" in source
    assert 'tailwind.generated.css' in source


def test_macos_compiles_before_pyinstaller():
    source = (ROOT / 'packaging/macos/build-macos.sh').read_text(encoding='utf-8')
    assert 'build_frontend_css' in source
    assert 'npm run build' in source
    assert source.index('build_frontend_css\n') < source.index('PYI=(')
    assert 'package-lock.json' in source


def test_docker_compiles_in_separate_stage():
    source = (ROOT / 'Dockerfile').read_text(encoding='utf-8')
    assert 'FROM node:22-bookworm-slim AS frontend' in source
    assert 'npm run build' in source
    assert 'COPY --from=frontend' in source
    assert source.index('npm run build') < source.index('FROM python:3.12-slim-bookworm')
