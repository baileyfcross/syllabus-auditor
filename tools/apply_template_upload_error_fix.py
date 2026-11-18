#!/usr/bin/env python3
"""Safely install structured master-template upload errors into Syllabus Auditor.

Run once from project root:
    python3 tools/apply_template_upload_error_fix.py

Fails without modifying anything if the upload route changed unexpectedly.
Backups are saved in build/patch-backups/template-upload/.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / 'app' / 'main.py'
APP_JS = ROOT / 'app' / 'static' / 'app.js'
MODULE = ROOT / 'app' / 'template_upload_errors.py'
BACKUP = ROOT / 'build' / 'patch-backups' / 'template-upload'

OLD_ROUTE = '''@app.post('/api/templates/upload')
async def upload_template(institution_id:int=Form(...),name:str=Form(...),academic_year:str=Form(''),notes:str=Form(''),is_default:bool=Form(False),file:UploadFile=File(...),user=Depends(admin)):
    assert_institution(institution_id)
    content=await file.read(MAX_UPLOAD+1);validate_upload(file.filename,content)
    filename=secrets.token_hex(16)+Path(file.filename).suffix.lower();path=UPLOAD_DIR/filename
    path.write_bytes(content)
    try:sections=template_sections(path)
    except Exception:
        path.unlink(missing_ok=True);raise
    try:
        with transaction() as db:
            if is_default:
                db.execute('UPDATE templates SET is_default=0 WHERE institution_id=?',(institution_id,))
            ident=db.execute(\'\'\'INSERT INTO templates(institution_id,name,academic_year,notes,doc_path,sections_json,is_default,created_at) VALUES(?,?,?,?,?,?,?,?)\'\'\',
                (institution_id,name[:180],academic_year[:30],notes[:2000],str(path),json.dumps([{**s,'required':True} for s in sections]),int(is_default),now())).lastrowid
    except Exception:
        path.unlink(missing_ok=True)
        raise
    log(user['id'],'template.create',str(ident));return {'id':ident,'sections':sections}
'''

NEW_ROUTE = '''@app.post('/api/templates/upload')
async def upload_template(institution_id:int=Form(...),name:str=Form(...),academic_year:str=Form(''),notes:str=Form(''),is_default:bool=Form(False),file:UploadFile=File(...),user=Depends(admin)):
    """Import DOCX/PDF template with private diagnostics for desktop failures."""
    assert_institution(institution_id)
    source_name = (file.filename or '').strip()
    if not source_name:
        fail('No template filename was received. Select a DOCX or PDF file and try again.',400)
    try:
        content = await file.read(MAX_UPLOAD+1)
    except Exception as exc:
        ref = record_template_upload_error(exc, 'read-upload', source_name)
        fail(f'Could not read the selected template file (reference {ref}).',500)
    validate_upload(source_name,content)
    filename=secrets.token_hex(16)+Path(source_name).suffix.lower();path=UPLOAD_DIR/filename
    try:
        path.write_bytes(content)
    except OSError as exc:
        ref = record_template_upload_error(exc, 'save-file', source_name)
        fail(f'Could not save the template on this computer (reference {ref}). Check storage permissions and free disk space.',500)
    try:
        sections=template_sections(path)
    except ValueError as exc:
        path.unlink(missing_ok=True)
        fail(f'The template could not be read: {exc}',400)
    except Exception as exc:
        path.unlink(missing_ok=True)
        ref = record_template_upload_error(exc, 'extract-sections', source_name)
        fail(f'Could not extract sections from the template (reference {ref}).',500)
    try:
        with transaction() as db:
            if is_default:
                db.execute('UPDATE templates SET is_default=0 WHERE institution_id=?',(institution_id,))
            ident=db.execute(\'\'\'INSERT INTO templates(institution_id,name,academic_year,notes,doc_path,sections_json,is_default,created_at) VALUES(?,?,?,?,?,?,?,?)\'\'\',
                (institution_id,name[:180],academic_year[:30],notes[:2000],str(path),json.dumps([{**s,'required':True} for s in sections]),int(is_default),now())).lastrowid
    except Exception as exc:
        path.unlink(missing_ok=True)
        ref = record_template_upload_error(exc, 'save-database', source_name)
        fail(f'Could not save the template record (reference {ref}).',500)
    # The document was committed successfully even if the activity log fails.
    try:
        log(user['id'],'template.create',str(ident))
    except Exception as exc:
        record_template_upload_error(exc, 'activity-log', source_name)
    return {'id':ident,'sections':sections}
'''

OLD_FETCH = ''' const resp=await fetch(url,{credentials:'same-origin',...opt,method,headers});
 if(!resp.ok){let msg='Request failed';try{const j=await resp.json();msg=typeof j.detail==='string'?j.detail:JSON.stringify(j.detail)}catch{}
  if(resp.status===401 && S.user){S.user=null;if(S.desktop&&!S.desktopPasswordRequired)notify('Your local session ended. Restart the desktop application to sign in again.','error');else loginUI()}
  throw Error(msg)}'''

NEW_FETCH = ''' let resp;
 try {resp=await fetch(url,{credentials:'same-origin',...opt,method,headers})}
 catch(err){throw Error(`Could not connect to the local Syllabus Auditor service: ${err?.message||'Network request failed'}`)}
 if(!resp.ok){let msg=`Request failed (HTTP ${resp.status}${resp.statusText?' '+resp.statusText:''})`;try{const j=await resp.json();if(j&&j.detail)msg=typeof j.detail==='string'?j.detail:JSON.stringify(j.detail)}catch{}
  if(resp.status===401 && S.user){S.user=null;if(S.desktop&&!S.desktopPasswordRequired)notify('Your local session ended. Restart the desktop application to sign in again.','error');else loginUI()}
  throw Error(msg)}'''


def main() -> int:
    if not (MAIN.is_file() and APP_JS.is_file() and MODULE.is_file()):
        print('ERROR: Run this script from a complete Syllabus Auditor checkout.', file=sys.stderr)
        return 2
    source_main = MAIN.read_text(encoding='utf-8')
    source_js = APP_JS.read_text(encoding='utf-8')
    already_main = 'record_template_upload_error(exc, \'extract-sections\'' in source_main
    already_js = 'Could not connect to the local Syllabus Auditor service:' in source_js
    if already_main and already_js:
        print('Master-template upload error patch is already installed.')
        return 0
    if not already_main and source_main.count(OLD_ROUTE) != 1:
        print('ERROR: The master-template upload route differs from the tested version. No files modified.', file=sys.stderr)
        return 3
    if not already_js and source_js.count(OLD_FETCH) != 1:
        print('ERROR: The request helper differs from the tested version. No files modified.', file=sys.stderr)
        return 3
    updated_main=source_main
    updated_js=source_js
    if not already_main:
        if 'from . import desktop_auth\n' not in source_main:
            print('ERROR: Unknown app/main.py imports. No files modified.', file=sys.stderr)
            return 3
        updated_main=source_main.replace('from . import desktop_auth\n','from . import desktop_auth\nfrom .template_upload_errors import record_template_upload_error\n',1).replace(OLD_ROUTE,NEW_ROUTE,1)
    if not already_js:
        updated_js=source_js.replace(OLD_FETCH,NEW_FETCH,1)
    BACKUP.mkdir(parents=True,exist_ok=True)
    if updated_main!=source_main:
        shutil.copy2(MAIN, BACKUP/'main.py.before-template-upload')
        MAIN.write_text(updated_main,encoding='utf-8')
    if updated_js!=source_js:
        shutil.copy2(APP_JS, BACKUP/'app.js.before-template-upload')
        APP_JS.write_text(updated_js,encoding='utf-8')
    print('Applied master-template upload diagnostics.')
    print('Previous copies saved in:', BACKUP)
    print('Restart source-mode app or rebuild installed .app before testing.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
