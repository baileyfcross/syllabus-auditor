"""Cross-platform checks for the native macOS launcher and build scripts.

Does not replace an actual Cocoa, PyInstaller, or notarization smoke test.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
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


@unittest.skipUnless((MAC / 'build-macos.sh').is_file(), 'Install the macOS packaging kit to test its build scripts')
class MacOSPackagingTests(unittest.TestCase):
    def test_shell_syntax(self):
        for name in ('build-macos.sh', 'preview-macos.sh'):
            if not (MAC / name).is_file():
                continue
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

    def test_native_bootstrap_uses_run_js_not_csp_eval(self):
        launcher = load_launcher()
        from app import desktop_auth

        class Window:
            def __init__(self):
                self.script = ''
                self.events = mock.Mock()
                self.events.loaded.wait.return_value = True
            def run_js(self, script):
                self.script = script
            def evaluate_js(self, script):
                raise AssertionError('evaluate_js must never be used under strict CSP')

        window = Window()
        with mock.patch.object(desktop_auth, 'password_required', return_value=False), \
             mock.patch.object(desktop_auth, 'bootstrap_script', return_value='bootstrap-from-header'), \
             mock.patch.object(launcher, '_session_created', return_value=True):
            launcher.unlock_native_window(window, 'secret', 8765)
        self.assertEqual(window.script, 'bootstrap-from-header')
        window.events.loaded.wait.assert_called_once_with(timeout=20)

    def test_password_lock_skips_injection(self):
        launcher = load_launcher()
        from app import desktop_auth
        window = mock.Mock()
        with mock.patch.object(desktop_auth, 'password_required', return_value=True):
            launcher.unlock_native_window(window, 'secret', 8765)
        window.run_js.assert_not_called()

    def test_unsuccessful_unlock_displays_error_instead_of_spinner(self):
        launcher = load_launcher()
        from app import desktop_auth
        window = mock.Mock()
        window.events.loaded.wait.return_value = True
        with mock.patch.object(desktop_auth, 'password_required', return_value=False), \
             mock.patch.object(desktop_auth, 'bootstrap_script', return_value='bootstrap-from-header'), \
             mock.patch.object(launcher, '_session_created', return_value=False), \
             mock.patch.object(launcher.time, 'sleep', return_value=None), \
             mock.patch.object(launcher, '_desktop_log') as logger:
            launcher.unlock_native_window(window, 'secret', 8765)
        self.assertEqual(window.run_js.call_count, 2)  # bootstrap, error UI
        self.assertIn('Desktop startup problem', window.run_js.call_args.args[0])
        self.assertTrue(logger.called)

    def test_page_load_failure_displays_diagnostic(self):
        launcher = load_launcher()
        from app import desktop_auth
        window = mock.Mock()
        window.events.loaded.wait.return_value = False
        with mock.patch.object(desktop_auth, 'password_required', return_value=False), \
             mock.patch.object(launcher, '_desktop_log'):
            launcher.unlock_native_window(window, 'secret', 8765)
        self.assertEqual(window.run_js.call_count, 1)
        self.assertIn('did not finish loading', window.run_js.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
