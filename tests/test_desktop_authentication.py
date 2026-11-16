"""Isolated desktop authentication tests; subprocesses avoid module env caching."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SECRET = 'mac-windows-launcher-secret-' + 'x' * 70


def launch_case(code, tmp_path, desktop=True, host='127.0.0.1'):
    env = os.environ.copy()
    env['SA_DATA_DIR'] = str(tmp_path)
    env['SA_HOST'] = host
    env.pop('SA_DESKTOP_BOOTSTRAP_SECRET', None)
    if desktop:
        env['SA_DESKTOP_BOOTSTRAP_SECRET'] = SECRET
    result = subprocess.run([sys.executable, '-c', textwrap.dedent(code)], cwd=ROOT,
                            env=env, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + '\n' + result.stderr
    return result.stdout


def test_hosted_login_remains_required(tmp_path):
    launch_case('''
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app) as c:
            b=c.get('/api/bootstrap').json()
            assert b['desktop_mode'] is False and b['needs_setup'] is True
            assert c.get('/api/institutions').status_code==401
            assert c.post('/api/desktop/unlock',headers={'X-SA-Desktop-Secret':'x'*80}).status_code==404
            assert c.post('/api/desktop/security',json={'require_password':False}).status_code==401
    ''',tmp_path,desktop=False)


def test_secret_does_not_enable_network_bound_server(tmp_path):
    launch_case('''
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app) as c:
            assert c.get('/api/bootstrap').json()['desktop_mode'] is False
            assert c.post('/api/desktop/unlock',headers={'X-SA-Desktop-Secret':'x'*80}).status_code==404
    ''',tmp_path,desktop=True,host='0.0.0.0')


def test_passwordless_login_one_time_and_csrf(tmp_path):
    launch_case('''
        from fastapi.testclient import TestClient
        from app.main import app
        from app import desktop_auth
        from app.database import one
        secret='mac-windows-launcher-secret-'+'x'*70
        assert desktop_auth.ENABLED
        assert secret not in __import__('os').environ.values()
        with TestClient(app,base_url='http://127.0.0.1:8765',client=('127.0.0.1',50000)) as c:
            boot=c.get('/api/bootstrap').json()
            assert boot['desktop_mode'] and not boot['needs_setup'] and not boot['desktop_password_required']
            assert c.get('/api/me').status_code==401
            assert c.get('/api/institutions').status_code==401
            assert c.post('/api/desktop/unlock').status_code==403
            assert c.post('/api/desktop/unlock',headers={'X-SA-Desktop-Secret':'wrong'}).status_code==403
            assert c.post('/api/desktop/unlock',headers={'X-SA-Desktop-Secret':secret,'Origin':'https://evil.test'}).status_code==403
            other=TestClient(app,base_url='http://127.0.0.1:8765',client=('192.0.2.1',50000))
            assert other.post('/api/desktop/unlock',headers={'X-SA-Desktop-Secret':secret}).status_code==403
            r=c.post('/api/desktop/unlock',headers={'X-SA-Desktop-Secret':secret})
            assert r.status_code==200,r.text
            assert 'httponly' in r.headers['set-cookie'].lower()
            assert c.get('/api/me').json()['username']=='desktop-local'
            assert c.get('/api/me').json()['role']=='admin'
            assert c.post('/api/institutions',json={'name':'Protected'}).status_code==403
            csrf=c.get('/api/me').json()['csrf']
            assert c.post('/api/institutions',json={'name':'Protected'},headers={'X-CSRF-Token':csrf}).status_code==200
            assert c.post('/api/desktop/unlock',headers={'X-SA-Desktop-Secret':secret}).status_code==403
            script=desktop_auth.bootstrap_script(secret,8765)
            assert "location.origin" in script and "X-SA-Desktop-Secret" in script
            assert '/api/desktop/unlock' in script and 'location.replace' in script
            assert c.get('/api/users').status_code==200
            assert all(x['username']!='desktop-local' for x in c.get('/api/users',headers={'X-CSRF-Token':csrf}).json())
            assert not one('SELECT id FROM users WHERE username=?',('auditor',))
        assert not one('SELECT token_hash FROM sessions WHERE user_id=(SELECT id FROM users WHERE username=?)',('desktop-local',))
    ''',tmp_path)


def test_optional_password_lock_requires_real_login(tmp_path):
    launch_case('''
        from fastapi.testclient import TestClient
        from app.main import app
        from app import desktop_auth
        secret='mac-windows-launcher-secret-'+'x'*70
        with TestClient(app,base_url='http://127.0.0.1:8765',client=('127.0.0.1',50000)) as c:
            r=c.post('/api/desktop/unlock',headers={'X-SA-Desktop-Secret':secret})
            assert r.status_code==200,r.text
            csrf=c.get('/api/me').json()['csrf'];c.headers['X-CSRF-Token']=csrf
            bad=c.post('/api/desktop/security',json={'require_password':True,'new_password':'short'})
            assert bad.status_code==400
            assert not desktop_auth.password_required()
            r=c.post('/api/desktop/security',json={'require_password':True,'new_password':'longer-than-12-chars'})
            assert r.status_code==200,r.text
            assert desktop_auth.password_required()
            assert c.get('/api/runtime').json()['desktop_password_required']
            assert c.post('/api/desktop/unlock',headers={'X-SA-Desktop-Secret':secret}).status_code==403
            assert c.post('/api/login',json={'username':'desktop-local','password':'wrong'}).status_code==401
            signin=c.post('/api/login',json={'username':'desktop-local','password':'longer-than-12-chars'})
            assert signin.status_code==200,signin.text
            assert signin.json()['role']=='admin'
            csrf=signin.json()['csrf']
            r=c.post('/api/desktop/security',json={'require_password':False},headers={'X-CSRF-Token':csrf})
            assert r.status_code==200,r.text
            assert not desktop_auth.password_required()
    ''',tmp_path)


def test_lock_survives_application_restart(tmp_path):
    launch_case('''
        from fastapi.testclient import TestClient
        from app.main import app
        from app import desktop_auth
        with TestClient(app,base_url='http://127.0.0.1:8765',client=('127.0.0.1',50000)) as c:
            x=c.post('/api/desktop/unlock',headers={'X-SA-Desktop-Secret':'mac-windows-launcher-secret-'+'x'*70})
            assert x.status_code==200
            csrf=c.get('/api/me').json()['csrf']
            assert c.post('/api/desktop/security',headers={'X-CSRF-Token':csrf},json={'require_password':True,'new_password':'saved-password-123456'}).status_code==200
    ''',tmp_path)
    launch_case('''
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app,base_url='http://127.0.0.1:8765',client=('127.0.0.1',50000)) as c:
            assert c.get('/api/bootstrap').json()['desktop_password_required']
            assert c.get('/api/me').status_code==401
            assert c.post('/api/desktop/unlock',headers={'X-SA-Desktop-Secret':'mac-windows-launcher-secret-'+'x'*70}).status_code==403
            assert c.post('/api/login',json={'username':'desktop-local','password':'saved-password-123456'}).status_code==200
    ''',tmp_path)
