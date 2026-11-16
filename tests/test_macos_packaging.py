"""Cross-platform checks for the macOS launcher and build scripts.

These tests do not imply that Cocoa, PyInstaller, OCR, or macOS signing was
executed. Final smoke tests must run on a Mac.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MAC = ROOT / 'packaging' / 'macos'


def load_launcher():
    spec = importlib.util.spec_from_file_location('syllabus_macos_launcher', MAC / 'desktop_launcher.py')
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless((MAC/'build-macos.sh').is_file(), 'Install the macOS packaging kit to test its build scripts')
class MacOSPackagingTests(unittest.TestCase):
    def test_shell_syntax(self):
        for name in ('build-macos.sh', 'preview-macos.sh'):
            result = subprocess.run(['bash', '-n', str(MAC / name)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_dry_run_does_not_build(self):
        completed = subprocess.run(
            ['bash', str(MAC / 'build-macos.sh'), '--dry-run', '--skip-ai', '--skip-ocr'],
            capture_output=True, text=True, check=True,
        )
        self.assertIn('No files were changed.', completed.stdout)
        self.assertIn('Qwen3 bundled: 0', completed.stdout)
        self.assertIn('Tesseract bundled: 0', completed.stdout)

    def test_configure_runtime_uses_private_data_directory_and_model_path(self):
        launcher = load_launcher()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / 'my data'
            with patch.object(launcher, 'bundled_root', return_value=root), patch.dict(
                os.environ, {'SA_DATA_DIR': str(data), 'SA_MODEL_PATH': 'outdated', 'SA_PORT': '8765'},
            ):
                returned = launcher.configure_runtime(29123)
                self.assertEqual(returned, data)
                self.assertTrue(data.is_dir())
                self.assertEqual(os.environ['SA_MODEL_PATH'], str(root / 'models' / launcher.MODEL_FILE))
                self.assertEqual(os.environ['SA_PORT'], '29123')
                self.assertEqual(os.environ['SA_HOST'], '127.0.0.1')

    def test_single_instance_lock(self):
        launcher = load_launcher()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            first = launcher.hold_single_instance(folder)
            try:
                with self.assertRaisesRegex(RuntimeError, 'already running'):
                    launcher.hold_single_instance(folder)
            finally:
                first.close()

    def test_native_bootstrap_uses_protected_token(self):
        launcher=load_launcher()
        from app import desktop_auth
        class Window:
            script=''
            def evaluate_js(self,script):
                self.script=script
                return True
        window=Window()
        with mock.patch.object(desktop_auth,'password_required',return_value=False), \
             mock.patch.object(desktop_auth,'bootstrap_script',return_value='bootstrap-from-header'):
            launcher.unlock_native_window(window,'secret',8765)
        self.assertEqual(window.script,'bootstrap-from-header')



if __name__ == '__main__':
    unittest.main()
