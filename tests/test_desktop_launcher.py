"""Platform-independent smoke tests for the Windows desktop entry point.
A real WebView2/inno installer must still be tested on Windows.
"""
from __future__ import annotations
import importlib.util
import os
import pathlib
import sys
import subprocess
import tempfile
import threading
import time
import types
from unittest import TestCase, mock

HERE=pathlib.Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('sa_native', HERE/'packaging'/'windows'/'desktop_launcher.py')
loader=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(loader)


class DesktopLauncherTests(TestCase):
    def test_runtime_uses_per_user_data_and_no_browser(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.dict(os.environ, {'LOCALAPPDATA':d}, clear=False):
                os.environ.pop('SA_DATA_DIR', None)
                _, data=loader.configure_runtime(45553)
                self.assertEqual(data, pathlib.Path(d)/'SyllabusAuditor'/'data')
                self.assertEqual(os.environ['SA_HOST'],'127.0.0.1')
                self.assertEqual(os.environ['SA_PORT'],'45553')
                self.assertTrue(data.is_dir())
            os.environ.pop('SA_DATA_DIR', None)

    def test_source_script_resolves_app_from_unrelated_working_directory(self):
        # Run with Python isolated mode: project root is NOT already on sys.path.
        launcher_path = HERE / 'packaging' / 'windows' / 'desktop_launcher.py'
        snippet = (
            'import importlib.util, sys; '
            'spec=importlib.util.spec_from_file_location("sa_desktop", sys.argv[1]); '
            'mod=importlib.util.module_from_spec(spec); '
            'spec.loader.exec_module(mod); '
            'root=mod.ensure_app_import_path(); '
            'assert (root / "app" / "main.py").is_file(); '
            'assert importlib.util.find_spec("app.main") is not None'
        )
        with tempfile.TemporaryDirectory() as unrelated_dir:
            result = subprocess.run(
                [sys.executable, '-I', '-c', snippet, str(launcher_path)],
                cwd=unrelated_dir,
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_port_dynamic_and_loopback_only(self):
        p=loader.select_port()
        self.assertGreater(p,0)
        self.assertEqual(loader.HOST,'127.0.0.1')

    def test_native_window_and_server_shutdown(self):
        with tempfile.TemporaryDirectory() as d:
            app_main=types.ModuleType('app.main')
            app_main.app=object()
            fake_app=types.ModuleType('app')
            fake_app.main=app_main
            fake_desktop_auth=types.ModuleType('app.desktop_auth')
            fake_desktop_auth.password_required=lambda:False
            fake_desktop_auth.bootstrap_script=lambda secret,port:'(() => true)()'
            start_calls=[]; windows=[]; servers=[]

            class FakeServer:
                def __init__(self, config):
                    self.config=config; self.started=False; self.should_exit=False
                    servers.append(self)
                def run(self):
                    self.started=True
                    while not self.should_exit:
                        time.sleep(.01)

            class FakeConfig:
                def __init__(self, **kwargs): self.kwargs=kwargs

            class FakeWindow:
                def evaluate_js(self, script): return True

            fake_uvicorn=types.ModuleType('uvicorn')
            fake_uvicorn.Server=FakeServer
            fake_uvicorn.Config=FakeConfig
            fake_webview=types.ModuleType('webview')
            fake_webview.settings={}
            def create_window(*args, **kwargs):
                windows.append((args,kwargs));return FakeWindow()
            def start(**kwargs):
                start_calls.append(kwargs)
                kwargs['func']()
            fake_webview.create_window=create_window
            fake_webview.start=start
            with mock.patch.dict(sys.modules, {'app':fake_app, 'app.main':app_main,'app.desktop_auth':fake_desktop_auth,'uvicorn':fake_uvicorn,'webview':fake_webview}):
                with mock.patch.dict(os.environ, {'SA_DATA_DIR':d}):
                    self.assertEqual(loader.main(),0)
            self.assertEqual(len(windows),1)
            self.assertEqual(len(start_calls),1)
            self.assertEqual(start_calls[0]['gui'],'edgechromium')
            self.assertEqual(fake_webview.settings['ALLOW_DOWNLOADS'],True)
            self.assertEqual(fake_webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'],True)
            self.assertTrue(windows[0][0][1].startswith('http://127.0.0.1:'))
            self.assertTrue(servers[0].should_exit)
            self.assertEqual(servers[0].config.kwargs['host'],'127.0.0.1')

    def test_native_one_time_token_is_not_in_window_url(self):
        class Window:
            script=''
            def evaluate_js(self, script):
                self.script=script
                return True
        from app import desktop_auth
        window=Window()
        with mock.patch.object(desktop_auth,'password_required',return_value=False), \
             mock.patch.object(desktop_auth,'bootstrap_script',return_value='secure-headers-only'):
            loader.unlock_native_window(window,'secret',8765)
        self.assertEqual(window.script,'secure-headers-only')



if __name__=='__main__':
    import unittest
    unittest.main()
