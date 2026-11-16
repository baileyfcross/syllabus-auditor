"""Syllabus Auditor - single-origin web application, embedded local AI, no external AI endpoints."""
import asyncio, csv, hashlib, hmac, io, json, os, re, secrets, shutil, threading, time, zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Request, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from .config import ROOT, DATA_DIR,UPLOAD_DIR,MAX_UPLOAD,SESSION_DAYS,MODEL_PATH,MONITOR_INTERVAL_HOURS
from .database import initialize,one,all_rows,execute,transaction,now,record_revision,log
from .documents import validate_upload,extract,template_sections,infer_course_code,correct_docx
from .validation import audit_document
from .sources import check_target,discover_course,refresh_institution,normalize_allowed_hosts
from .catalog_bulk import scan_catalog,apply_import,create_browser_capture_import,MAX_PAGES,_self_service
from .reports import load,pdf_report,docx_report,csv_report,batch_zip
from .approval import build_approved_syllabus, review_summary
from .ai import ai
from . import desktop_auth

app=FastAPI(title='Syllabus Auditor',version='1.0.0',docs_url=None,redoc_url=None)
app.mount('/assets',StaticFiles(directory=ROOT/'app'/'static'),name='assets')
executor=ThreadPoolExecutor(max_workers=2,thread_name_prefix='audit')
STOP=threading.Event()
TOKEN_FILE=DATA_DIR/'bootstrap-token.txt'
DESKTOP_SESSIONS=set()

class UserError(Exception):pass

def fail(message,status=400):raise HTTPException(status_code=status,detail=message)
def nint(value,label='ID'):
    try:
        value=int(value)
        if value<1:raise ValueError()
        return value
    except (TypeError,ValueError):fail(f'Invalid {label}')

def pbkdf(password,salt=None):
    salt=salt or secrets.token_bytes(16)
    value=hashlib.pbkdf2_hmac('sha256',password.encode('utf-8'),salt,390000)
    return 'pbkdf2_sha256$390000$'+salt.hex()+'$'+value.hex()
def valid_password(password,stored):
    try:
        algo,count,salt,digest=stored.split('$')
        if algo!='pbkdf2_sha256':return False
        value=hashlib.pbkdf2_hmac('sha256',password.encode('utf-8'),bytes.fromhex(salt),int(count))
        return hmac.compare_digest(value.hex(),digest)
    except Exception:return False

def token_hash(token):return hashlib.sha256(token.encode()).hexdigest()

def current_user(request:Request):
    token=request.cookies.get('sa_session','')
    if not token: fail('Authentication required',401)
    session=one('SELECT s.csrf,s.expires_at,u.id,u.username,u.role FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?',(token_hash(token),))
    if not session or session['expires_at']<now():fail('Session expired',401)
    if request.method not in ('GET','HEAD','OPTIONS'):
        if not hmac.compare_digest(request.headers.get('x-csrf-token',''),session['csrf']):fail('CSRF token missing or invalid',403)
        origin=request.headers.get('origin','')
        if origin:
            from urllib.parse import urlsplit
            host=urlsplit(origin).netloc
            if host!=request.headers.get('host',''):fail('Cross-site request blocked',403)
    return session

def admin(user=Depends(current_user)):
    if user['role']!='admin':fail('Administrator permission required',403)
    return user

def data_fields(req,fields):
    return {k:req.get(k) for k in fields if k in req}

def pick(item,allowed):return {k:v for k,v in item.items() if k in allowed}

def assert_institution(ident):
    r=one('SELECT * FROM institutions WHERE id=?',(nint(ident),))
    if not r:fail('Institution not found',404)
    return r

def assert_template(ident,inst_id=None):
    r=one('SELECT * FROM templates WHERE id=?',(nint(ident),))
    if not r or inst_id is not None and r['institution_id']!=inst_id: fail('Template not found for institution',404)
    return r

def reference_for_course(inst_id,code,year):
    if not code:return None
    return (one('SELECT * FROM courses WHERE institution_id=? AND UPPER(code)=? AND academic_year=?',(inst_id,code.upper(),year))
            or one('SELECT * FROM courses WHERE institution_id=? AND UPPER(code)=? AND academic_year=""',(inst_id,code.upper())))

def run_job(job_id):
    job=one('SELECT * FROM audit_jobs WHERE id=?',(job_id,))
    if not job:return
    execute('UPDATE audit_jobs SET status="running" WHERE id=?',(job_id,))
    records=all_rows('SELECT * FROM audits WHERE job_id=? AND status="queued" ORDER BY id',(job_id,))
    reqs=all_rows('SELECT * FROM requirements WHERE institution_id=? AND active=1 AND (template_id IS NULL OR template_id=?) ORDER BY id',(job['institution_id'],job['template_id']))
    template=one('SELECT * FROM templates WHERE id=?',(job['template_id'],)) if job['template_id'] else None
    had_error=False
    for audit in records:
        try:
            execute('UPDATE audits SET status="running" WHERE id=?',(audit['id'],))
            extracted=extract(audit['storage_path'])
            code=infer_course_code(extracted['text'])
            course=reference_for_course(job['institution_id'],code,job['academic_year'])
            valid_reqs=[]
            for requirement in reqs:
                dept=(requirement.get('department') or '').strip().upper()
                if dept and code and not code.startswith(dept+'-'):continue
                # Exclude date-disjoint requirements only; overlapping policies remain in scope.
                year=re.search(r'(20\d\d)',job['academic_year'] or '')
                if year:
                    start_year=int(year.group(1))
                    start=f'{start_year}-01-01'; end=f'{start_year+1}-12-31'
                    if requirement.get('effective_from') and requirement['effective_from']>end:continue
                    if requirement.get('effective_to') and requirement['effective_to']<start:continue
                valid_reqs.append(requirement)
            found_code,findings=audit_document(extracted,valid_reqs,course,template,use_ai=True)
            if not extracted['text'].strip():had_error=True
            counts={state:sum(f['status']==state for f in findings) for state in ('passed','warning','failed','review')}
            with transaction() as db:
                for f in findings:
                    db.execute('''INSERT INTO findings(audit_id,requirement_id,code,title,category,status,severity,observed,expected,explanation,source_url,location,confidence,evidence_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (audit['id'],f['requirement_id'],f['code'],f['title'],f['category'],f['status'],f['severity'],f['observed'],f['expected'],f['explanation'],f['source_url'],f['location'],f['confidence'],f['evidence_json']))
                db.execute('''UPDATE audits SET status="complete",course_code=?,passed=?,warnings=?,failed=?,review=?,extraction_text=?,extraction_json=?,completed_at=? WHERE id=?''',
                (found_code or code,counts['passed'],counts['warning'],counts['failed'],counts['review'],extracted['text'][:150000],json.dumps(extracted['blocks'][:5000]),now(),audit['id']))
        except Exception as exc:
            had_error=True
            execute('UPDATE audits SET status="error",error=?,completed_at=? WHERE id=?',(str(exc)[:500],now(),audit['id']))
        finally:
            execute('UPDATE audit_jobs SET finished=finished+1 WHERE id=?',(job_id,))
    execute('UPDATE audit_jobs SET status=?,finished_at=? WHERE id=?',('complete_with_errors' if had_error else 'complete',now(),job_id))

def _monitor():
    # Startup grace; no retrieval without official configured URLs.
    if STOP.wait(30):return
    while not STOP.is_set():
        try:
            institutions=all_rows('SELECT * FROM institutions WHERE active=1')
            for inst in institutions:
                if STOP.is_set():return
                candidates=all_rows('''SELECT target_type,target_id,MAX(checked_at) AS checked_at FROM source_checks WHERE institution_id=? GROUP BY target_type,target_id''',(inst['id'],))
                checked={(x['target_type'],x['target_id']):x['checked_at'] for x in candidates}
                for table,name in [('courses','course'),('requirements','requirement')]:
                    for row in all_rows(f'SELECT id FROM {table} WHERE institution_id=? AND source_url!=""',(inst['id'],)):
                        latest=checked.get((name,row['id']))
                        if latest:
                            try:
                                if (datetime.now(timezone.utc)-datetime.fromisoformat(latest)).total_seconds()<MONITOR_INTERVAL_HOURS*3600: continue
                            except ValueError:pass
                        check_target(inst,name,row['id'])
        except Exception as exc:print('Source monitor:',str(exc)[:180],flush=True)
        if STOP.wait(60*60):return

@app.on_event('startup')
def startup():
    initialize()
    if desktop_auth.ENABLED:
        # A local-only identity is needed for audit FKs, review ownership, and
        # the existing authorization code. A randomly chosen password prevents
        # the auto-login identity from being usable as a normal hosted account.
        with transaction() as db:
            row = db.execute('SELECT id FROM users WHERE username=?', (desktop_auth.DESKTOP_USER,)).fetchone()
            if not row:
                db.execute('INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,?,?)',
                           (desktop_auth.DESKTOP_USER, pbkdf(secrets.token_urlsafe(48)), 'admin', now()))
            else:
                db.execute('UPDATE users SET role=? WHERE username=?', ('admin', desktop_auth.DESKTOP_USER))
            # In desktop mode, invalidate old local cookies at every launch.
            # This also ensures an optional startup lock cannot be bypassed by
            # an admin session cached from an earlier source-mode launch.
            db.execute('DELETE FROM sessions')
        TOKEN_FILE.unlink(missing_ok=True)
    elif not one('SELECT id FROM users WHERE username!=? LIMIT 1',(desktop_auth.DESKTOP_USER,)):
        if not TOKEN_FILE.exists():TOKEN_FILE.write_text(secrets.token_urlsafe(24))
        try:os.chmod(TOKEN_FILE,0o600)
        except OSError:pass
        print('\nSYLLABUS AUDITOR FIRST-RUN SETUP TOKEN:',TOKEN_FILE.read_text().strip(),'\n',flush=True)
    else:TOKEN_FILE.unlink(missing_ok=True)
    STOP.clear()
    thread=threading.Thread(target=_monitor,daemon=True,name='source-monitor');thread.start()

@app.on_event('shutdown')
def shutdown():
    STOP.set()
    for digest in list(DESKTOP_SESSIONS):
        execute('DELETE FROM sessions WHERE token_hash=?', (digest,))
    DESKTOP_SESSIONS.clear()
    executor.shutdown(wait=False,cancel_futures=True)

@app.exception_handler(ValueError)
async def validation_error_handler(request:Request, exc:ValueError):
    return JSONResponse({'detail':str(exc)},status_code=400)

@app.middleware('http')
async def security_headers(request:Request,call_next):
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Permissions-Policy']='camera=(), microphone=(), geolocation=()'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    response.headers['Cache-Control']='no-store' if request.url.path.startswith('/api/') else 'no-cache'
    return response

@app.get('/',response_class=HTMLResponse)
def index():return (ROOT/'app'/'static'/'index.html').read_text(encoding='utf-8')
@app.get('/health')
def health():return {'ok':True,'product':'Syllabus Auditor','version':'1.0.0'}
@app.get('/api/bootstrap')
def bootstrap():
    return {'needs_setup':not desktop_auth.ENABLED and not bool(one('SELECT id FROM users WHERE username!=? LIMIT 1',
                                                          (desktop_auth.DESKTOP_USER,))),
            'version':'1.0.0', 'desktop_mode':desktop_auth.ENABLED,
            'desktop_password_required':desktop_auth.password_required() if desktop_auth.ENABLED else False}

@app.post('/api/desktop/unlock')
def desktop_unlock(request:Request):
    """One-time native-WebView handshake; not available in hosted web mode."""
    if not desktop_auth.ENABLED:
        fail('Not found',404)
    client = request.client.host if request.client else ''
    host = request.headers.get('host','')
    if client != '127.0.0.1' or not re.fullmatch(r'127\.0\.0\.1:\d{1,5}',host):
        fail('Local desktop connection required',403)
    origin = request.headers.get('origin','')
    if origin and origin != f'http://{host}':
        fail('Invalid origin',403)
    secret = request.headers.get('x-sa-desktop-secret','')
    if not desktop_auth.consume_secret(secret):
        fail('Desktop unlock not authorized',403)
    user=one('SELECT id,username,role FROM users WHERE username=?',(desktop_auth.DESKTOP_USER,))
    if not user:fail('Desktop identity not initialized',503)
    token = secrets.token_urlsafe(48)
    csrf = secrets.token_urlsafe(24)
    expiry=(datetime.now(timezone.utc)+timedelta(hours=12)).isoformat(timespec='seconds')
    digest=token_hash(token)
    execute('INSERT INTO sessions(token_hash,user_id,csrf,expires_at) VALUES(?,?,?,?)',
            (digest,user['id'],csrf,expiry))
    DESKTOP_SESSIONS.add(digest)
    response=JSONResponse({'ok':True})
    response.set_cookie('sa_session',token,max_age=12*3600,httponly=True,secure=False,samesite='strict',path='/')
    return response

@app.post('/api/desktop/security')
async def desktop_security(request:Request,user=Depends(admin)):
    if not desktop_auth.ENABLED:fail('Not found',404)
    body=await request.json()
    enabled=body.get('require_password')
    if type(enabled) is not bool:fail('require_password must be a boolean')
    local=one('SELECT id FROM users WHERE username=?',(desktop_auth.DESKTOP_USER,))
    if not local:fail('Desktop identity missing',503)
    if enabled:
        password=str(body.get('new_password',''))
        if len(password)<12:fail('Choose a startup password of at least 12 characters')
        execute('UPDATE users SET password_hash=? WHERE id=?',(pbkdf(password),local['id']))
    desktop_auth.set_password_required(enabled)
    return {'ok':True,'require_password':enabled,'effective':'next_launch'}

@app.post('/api/setup')
async def setup(request:Request):
    if desktop_auth.ENABLED or one('SELECT id FROM users WHERE username!=? LIMIT 1',(desktop_auth.DESKTOP_USER,)):fail('Already configured',403)
    body=await request.json();provided=str(body.get('token',''))
    if not TOKEN_FILE.exists() or not hmac.compare_digest(provided,TOKEN_FILE.read_text().strip()):fail('Invalid first-run setup token',403)
    username=str(body.get('username','')).strip().lower();password=str(body.get('password',''))
    if not re.fullmatch(r'[a-z0-9._-]{3,40}',username):fail('Username must be 3-40 characters (letters, numbers, dot, hyphen or underscore)')
    if len(password)<12:fail('Password must be 12 characters or longer')
    execute('INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,?,?)',(username,pbkdf(password),'admin',now()))
    TOKEN_FILE.unlink(missing_ok=True);return {'ok':True}

@app.post('/api/login')
async def login(request:Request):
    body=await request.json();username=str(body.get('username','')).strip().lower()
    user=one('SELECT * FROM users WHERE username=?',(username,))
    if username==desktop_auth.DESKTOP_USER and (not desktop_auth.ENABLED or not desktop_auth.password_required()):fail('Incorrect username or password',401)
    if not user or not valid_password(str(body.get('password','')),user['password_hash']):
        await asyncio.sleep(.3)
        fail('Incorrect username or password',401)
    raw=secrets.token_urlsafe(36); csrf=secrets.token_urlsafe(24)
    expires=(datetime.now(timezone.utc)+timedelta(days=SESSION_DAYS)).isoformat(timespec='seconds')
    execute('INSERT INTO sessions(token_hash,user_id,csrf,expires_at) VALUES(?,?,?,?)',(token_hash(raw),user['id'],csrf,expires))
    response=JSONResponse({'id':user['id'],'username':user['username'],'role':user['role'],'csrf':csrf,'ai':ai.status()})
    from .config import SECURE_COOKIES
    response.set_cookie('sa_session',raw,max_age=SESSION_DAYS*86400,httponly=True,secure=SECURE_COOKIES,samesite='strict',path='/')
    log(user['id'],'login')
    return response
@app.post('/api/logout')
def logout(request:Request,user=Depends(current_user)):
    execute('DELETE FROM sessions WHERE token_hash=?',(token_hash(request.cookies.get('sa_session','')),))
    response=JSONResponse({'ok':True});response.delete_cookie('sa_session',path='/');return response
@app.get('/api/me')
def me(user=Depends(current_user)):
    return {'id':user['id'],'username':user['username'],'role':user['role'],'csrf':user['csrf'],'ai':ai.status()}
@app.get('/api/overview')
def overview(user=Depends(current_user)):
    return {'institutions':one('SELECT COUNT(*) as n FROM institutions')['n'],
            'templates':one('SELECT COUNT(*) as n FROM templates')['n'],
            'audits':one('SELECT COUNT(DISTINCT COALESCE(series_id,id)) as n FROM audits')['n'],
            'counts':{status:one('''SELECT COUNT(*) AS n FROM findings f JOIN audits a ON a.id=f.audit_id
                 WHERE a.id=(SELECT MAX(z.id) FROM audits z WHERE COALESCE(z.series_id,z.id)=COALESCE(a.series_id,a.id))
                 AND f.status=? AND f.accepted=0 AND f.dismissed=0''',(status,))['n'] for status in ('passed','warning','failed','review')},
            'recent':all_rows('''SELECT a.id,a.series_id,a.filename,a.course_code,a.status,a.approved_at,a.passed,a.warnings,a.failed,a.review,a.created_at,
                                  (SELECT COUNT(*) FROM findings f WHERE f.audit_id=a.id AND f.status='failed' AND f.accepted=0 AND f.dismissed=0) AS pending_failed
                                  FROM audits a WHERE a.id=(SELECT MAX(z.id) FROM audits z WHERE COALESCE(z.series_id,z.id)=COALESCE(a.series_id,a.id))
                                  ORDER BY a.id DESC LIMIT 10'''),
            'source_alerts':one('SELECT COUNT(*) AS n FROM source_checks WHERE status IN ("changed","needs_review") AND approved_at=""')['n'],
            'ai':ai.status()}

@app.get('/api/institutions')
def institutions(user=Depends(current_user)):return all_rows('SELECT * FROM institutions ORDER BY name')
@app.post('/api/institutions')
async def create_institution(request:Request,user=Depends(admin)):
    body=await request.json();name=str(body.get('name','')).strip()
    if not name or len(name)>180:fail('Institution name is required')
    url=str(body.get('catalog_url','')).strip()
    if url and not url.startswith('https://'):fail('Catalog URL must use HTTPS')
    try: hosts=normalize_allowed_hosts(body.get('allowed_hosts',''))
    except ValueError as exc:fail(str(exc))
    if len(hosts)>500:fail('Approved domains list is too long')
    ident=execute('''INSERT INTO institutions(name,short_name,catalog_url,catalog_url_pattern,allowed_hosts,academic_year,created_at) VALUES(?,?,?,?,?,?,?)''',
        (name,str(body.get('short_name',''))[:60],url,str(body.get('catalog_url_pattern',''))[:1000],hosts,str(body.get('academic_year',''))[:30],now()))
    log(user['id'],'institution.create',str(ident));return {'id':ident}
@app.put('/api/institutions/{ident}')
async def update_institution(ident:int,request:Request,user=Depends(admin)):
    old=assert_institution(ident);body=await request.json()
    allowed=['name','short_name','catalog_url','catalog_url_pattern','allowed_hosts','academic_year','active']
    values=pick(body,allowed)
    if 'catalog_url' in values and values['catalog_url'] and not str(values['catalog_url']).startswith('https://'):fail('Only HTTPS catalog URLs are supported')
    if 'name' in values and not str(values['name']).strip():fail('Name required')
    if 'allowed_hosts' in values:
        try: values['allowed_hosts']=normalize_allowed_hosts(values['allowed_hosts'])
        except ValueError as exc:fail(str(exc))
        if len(values['allowed_hosts'])>500:fail('Approved domains list is too long')
    if not values:fail('No changes supplied')
    with transaction() as db:db.execute('UPDATE institutions SET '+','.join(f'{k}=?' for k in values)+' WHERE id=?',(*values.values(),ident))
    record_revision('institution',ident,old,values,user['id']);return {'ok':True}

@app.get('/api/templates')
def templates(institution_id:Optional[int]=None,user=Depends(current_user)):
    if institution_id:return all_rows('SELECT * FROM templates WHERE institution_id=? ORDER BY id DESC',(institution_id,))
    return all_rows('SELECT * FROM templates ORDER BY id DESC')
@app.post('/api/templates/upload')
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
            ident=db.execute('''INSERT INTO templates(institution_id,name,academic_year,notes,doc_path,sections_json,is_default,created_at) VALUES(?,?,?,?,?,?,?,?)''',
                (institution_id,name[:180],academic_year[:30],notes[:2000],str(path),json.dumps([{**s,'required':True} for s in sections]),int(is_default),now())).lastrowid
    except Exception:
        path.unlink(missing_ok=True)
        raise
    log(user['id'],'template.create',str(ident));return {'id':ident,'sections':sections}
@app.put('/api/templates/{ident}')
async def update_template(ident:int,request:Request,user=Depends(admin)):
    old=assert_template(ident);body=await request.json()
    values=pick(body,['name','academic_year','notes','active','sections_json','is_default'])
    if 'sections_json' in values:
        if isinstance(values['sections_json'],list):values['sections_json']=json.dumps(values['sections_json'])
        parsed=json.loads(values['sections_json'])
        if not isinstance(parsed,list) or len(parsed)>120:fail('Invalid section list')
        for item in parsed:
            if not isinstance(item,dict) or not isinstance(item.get('heading'),str) or len(item['heading'])>180:fail('Invalid template heading')
            if item.get('mode','heading') not in ('heading','present','exact','semantic'):fail('Invalid template matching mode')
            aliases=item.get('alternative_headings',[])
            if not isinstance(aliases,list) or len(aliases)>20 or any(not isinstance(alias,str) or not alias.strip() or len(alias)>180 or any(ord(c)<32 for c in alias) for alias in aliases):
                fail('Alternative headings must be a list of up to 20 nonempty headings, each 180 characters or fewer')
    if not values:fail('No changes supplied')
    for key in ('active','is_default'):
        if key in values:
            if not isinstance(values[key],bool) and values[key] not in (0,1):fail(f'Invalid {key}')
            values[key]=int(bool(values[key]))
    if values.get('is_default') and not values.get('active',old['active']):
        fail('Activate the template before setting it as the default')
    if values.get('active',old['active'])==0:
        values['is_default']=0
    values['version']=old['version']+1
    with transaction() as db:
        if values.get('is_default'):
            db.execute('UPDATE templates SET is_default=0 WHERE institution_id=? AND id!=?',(old['institution_id'],ident))
        db.execute('UPDATE templates SET '+','.join(f'{k}=?' for k in values)+' WHERE id=?',(*values.values(),ident))
    record_revision('template',ident,old,values,user['id']);return {'ok':True,'version':values['version']}
@app.delete('/api/templates/{ident}')
def delete_template(ident:int,user=Depends(admin)):
    """Remove a template without changing the saved findings of earlier audits."""
    old=assert_template(ident)
    busy=one("""SELECT id FROM audit_jobs WHERE template_id=? AND status IN ('queued','running') LIMIT 1""",(ident,))
    if not busy:
        busy=one("""SELECT id FROM audits WHERE template_id=? AND status IN ('queued','running') LIMIT 1""",(ident,))
    if busy:fail('Template is in use by an active audit. Wait for that audit to finish.',409)
    assigned=one('SELECT COUNT(*) AS total FROM requirements WHERE template_id=?',(ident,))['total']
    with transaction() as db:
        # A deleted template must not cause scoped policies to become global rules.
        db.execute('UPDATE requirements SET template_id=NULL,active=0,updated_at=? WHERE template_id=?',(now(),ident))
        # Audit reports keep their stored findings; missing template references become NULL.
        db.execute('UPDATE audit_jobs SET template_id=NULL WHERE template_id=?',(ident,))
        db.execute('UPDATE audits SET template_id=NULL WHERE template_id=?',(ident,))
        db.execute('DELETE FROM templates WHERE id=?',(ident,))
    # Only delete generated uploads inside the application-managed upload directory.
    storage=Path(old['doc_path']) if old['doc_path'] else None
    removed=False
    if storage and storage.is_absolute() and storage.resolve().is_relative_to(UPLOAD_DIR.resolve()):
        if not one('SELECT id FROM templates WHERE doc_path=? LIMIT 1',(str(storage),)):
            try: storage.unlink(missing_ok=True);removed=True
            except OSError:pass
    record_revision('template.delete',ident,old,{'deleted':True,'assigned_policies_disabled':assigned},user['id'])
    log(user['id'],'template.delete',str(ident),f'{old["name"]}; linked policies disabled: {assigned}')
    return {'ok':True,'disabled_linked_policies':assigned,'stored_file_removed':removed}

@app.get('/api/templates/{ident}/file')
def template_file(ident:int,user=Depends(current_user)):
    row=assert_template(ident);p=Path(row['doc_path'])
    if not p.is_file():fail('Template file missing',404)
    return FileResponse(p,filename=row['name']+p.suffix)

REQ_FIELDS=['name','category','mode','severity','expected_text','variants_json','keywords','source_url','effective_from','effective_to','department','active','template_id']
@app.get('/api/requirements')
def requirements(institution_id:int,user=Depends(current_user)):
    return all_rows('SELECT * FROM requirements WHERE institution_id=? ORDER BY category,name',(institution_id,))
@app.post('/api/requirements')
async def create_requirement(request:Request,user=Depends(admin)):
    body=await request.json();iid=nint(body.get('institution_id'));assert_institution(iid)
    if body.get('template_id'):assert_template(body['template_id'],iid)
    if body.get('mode','exact') not in ('exact','semantic','present','heading'):fail('Invalid matching mode')
    if body.get('severity','critical') not in ('critical','warning','info'):fail('Invalid severity')
    name=str(body.get('name','')).strip()
    if not name:fail('Name required')
    if body.get('source_url') and not str(body['source_url']).startswith('https://'):fail('Official source URL must be HTTPS')
    variants=body.get('variants_json',[])
    if isinstance(variants,list):variants=json.dumps(variants)
    try:
        if not isinstance(json.loads(variants),list):raise ValueError()
    except Exception:fail('Approved variants must be a JSON list')
    ident=execute('''INSERT INTO requirements(institution_id,template_id,name,category,mode,severity,expected_text,variants_json,keywords,source_url,effective_from,effective_to,department,created_at,updated_at)
       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (iid,body.get('template_id') or None,name[:180],body.get('category','policy'),body.get('mode','exact'),body.get('severity','critical'),body.get('expected_text',''),variants,body.get('keywords',''),body.get('source_url',''),body.get('effective_from',''),body.get('effective_to',''),body.get('department',''),now(),now()))
    log(user['id'],'requirement.create',str(ident));return {'id':ident}
@app.put('/api/requirements/{ident}')
async def update_requirement(ident:int,request:Request,user=Depends(admin)):
    old=one('SELECT * FROM requirements WHERE id=?',(ident,))
    if not old:fail('Requirement not found',404)
    body=await request.json();values=pick(body,REQ_FIELDS)
    if 'template_id' in values and values['template_id']:assert_template(values['template_id'],old['institution_id'])
    if values.get('mode',old['mode']) not in ('exact','semantic','present','heading'):fail('Invalid mode')
    if values.get('severity',old['severity']) not in ('critical','warning','info'):fail('Invalid severity')
    if 'variants_json' in values and isinstance(values['variants_json'],list):values['variants_json']=json.dumps(values['variants_json'])
    if 'variants_json' in values:
        try:assert isinstance(json.loads(values['variants_json']),list)
        except Exception:fail('Invalid variants list')
    if not values:fail('No changes supplied')
    if values.get('source_url') and not str(values['source_url']).startswith('https://'):fail('Official source URL must be HTTPS')
    values.update({'version':old['version']+1,'updated_at':now()})
    with transaction() as db:db.execute('UPDATE requirements SET '+','.join(f'{k}=?' for k in values)+' WHERE id=?',(*values.values(),ident))
    record_revision('requirement',ident,old,values,user['id']);return {'ok':True}

@app.delete('/api/requirements/{ident}')
def delete_requirement(ident:int,user=Depends(admin)):
    old=one('SELECT * FROM requirements WHERE id=?',(ident,))
    if not old:fail('Requirement not found',404)
    # Existing findings store the comparison text and outcome independently.
    with transaction() as db:
        db.execute("DELETE FROM source_checks WHERE target_type='requirement' AND target_id=? AND institution_id=?",
                   (ident,old['institution_id']))
        db.execute('DELETE FROM requirements WHERE id=?',(ident,))
    record_revision('requirement.delete',ident,old,{'deleted':True},user['id'])
    log(user['id'],'requirement.delete',str(ident),old['name'])
    return {'ok':True}

@app.get('/api/catalog-imports')
def catalog_imports(institution_id:int,user=Depends(current_user)):
    assert_institution(institution_id)
    return all_rows('SELECT id,institution_id,seed_url,subject_codes,academic_year,status,max_pages,pages_scanned,courses_found,truncated,error,created_at,finished_at FROM catalog_imports WHERE institution_id=? ORDER BY id DESC LIMIT 30',(institution_id,))

@app.post('/api/catalog-imports')
async def catalog_scan_start(request:Request,user=Depends(admin)):
    body=await request.json()
    inst=assert_institution(nint(body.get('institution_id')))
    seed=str(body.get('seed_url') or inst['catalog_url'] or '').strip()
    if not seed:fail('Configure the official catalog URL in institution settings first')
    from .sources import validate_url
    validate_url(seed,inst)
    # MyOCC supports one or many public subject searches in a background batch.
    # Non-MyOCC scans continue using their existing Acalog filter behavior.
    subject_codes=''
    if _self_service(seed):
        raw=body.get('subject_codes') or ''
        if isinstance(raw,list):raw=','.join(str(x) for x in raw)
        codes=[c.strip().upper() for c in str(raw).replace(';',',').split(',') if c.strip()]
        if len(codes)>150 or any(not re.fullmatch(r'[A-Z]{2,6}',c) for c in codes):
            fail('Use up to 150 subject codes, such as CIS,CSC,MATH')
        subject_codes=','.join(dict.fromkeys(codes))
    academic_year=str(body.get('academic_year') or inst['academic_year'] or '').strip()[:30]
    if not academic_year:fail('Choose a catalog academic year before scanning')
    try:max_pages=int(body.get('max_pages') or 1000)
    except (ValueError,TypeError):fail('Invalid page limit')
    if max_pages<1 or max_pages>MAX_PAGES:fail(f'Page limit must be between 1 and {MAX_PAGES}')
    running=one('SELECT id FROM catalog_imports WHERE institution_id=? AND status="running"',(inst['id'],))
    if running:fail(f'A catalog scan is already running (#{running["id"]})',409)
    ident=execute('INSERT INTO catalog_imports(institution_id,created_by,seed_url,subject_codes,academic_year,max_pages,created_at) VALUES(?,?,?,?,?,?,?)',
                  (inst['id'],user['id'],seed,subject_codes,academic_year,max_pages,now()))
    executor.submit(scan_catalog,ident,inst)
    log(user['id'],'catalog.scan.start',str(ident))
    return {'id':ident,'status':'running'}

@app.post('/api/catalog-imports/capture')
async def catalog_browser_capture(institution_id:int=Form(...), academic_year:str=Form(...),
                                  seed_url:str=Form(...),file:UploadFile=File(...),
                                  user=Depends(admin)):
    inst=assert_institution(institution_id)
    name=(file.filename or '').lower()
    if not name.endswith(('.json','.html','.htm')):
        fail('Select a catalog .json capture or saved .html page')
    blob=await file.read(20_000_001)
    if len(blob)>20_000_000:fail('Catalog capture exceeds 20 MB')
    result=await asyncio.to_thread(create_browser_capture_import,inst,user['id'],academic_year,seed_url,blob,name)
    log(user['id'],'catalog.capture.import',str(result['id']))
    return result

@app.get('/api/catalog-imports/{ident}')
def catalog_scan_status(ident:int,user=Depends(current_user)):
    job=one('SELECT * FROM catalog_imports WHERE id=?',(ident,))
    if not job:fail('Catalog scan not found',404)
    counts=all_rows('SELECT status,COUNT(*) count FROM catalog_import_items WHERE import_id=? GROUP BY status',(ident,))
    job['counts']={r['status']:r['count'] for r in counts}
    try:job['errors']=json.loads(job.pop('errors_json') or '[]')
    except ValueError:job['errors']=[]
    return job

@app.get('/api/catalog-imports/{ident}/items')
def catalog_scan_items(ident:int,offset:int=0,limit:int=100,q:str='',user=Depends(current_user)):
    if not one('SELECT id FROM catalog_imports WHERE id=?',(ident,)):fail('Catalog scan not found',404)
    if offset<0 or not 1<=limit<=200:fail('Invalid paging parameters')
    q=q.strip().upper()[:60]
    params=[ident];where='import_id=?'
    if q:
        where+=' AND (code LIKE ? OR UPPER(title) LIKE ?)'
        params.extend(['%'+q+'%','%'+q+'%'])
    total=one(f'SELECT COUNT(*) total FROM catalog_import_items WHERE {where}',params)['total']
    rows=all_rows(f'SELECT id,code,title,description,credits,prerequisites,source_url,status FROM catalog_import_items WHERE {where} ORDER BY code LIMIT ? OFFSET ?',(*params,limit,offset))
    return {'total':total,'items':rows,'offset':offset,'limit':limit}

@app.post('/api/catalog-imports/{ident}/apply')
async def catalog_scan_apply(ident:int,request:Request,user=Depends(admin)):
    job=one('SELECT id FROM catalog_imports WHERE id=?',(ident,))
    if not job:fail('Catalog scan not found',404)
    body=await request.json()
    if not isinstance(body.get('update_existing',False),bool):fail('Invalid update_existing value')
    return await asyncio.to_thread(apply_import,ident,user['id'],body.get('update_existing',False))

COURSE_FIELDS=['code','title','description','credits','prerequisites','academic_year','source_url']
@app.get('/api/courses')
def courses(institution_id:int,user=Depends(current_user)):
    return all_rows('SELECT * FROM courses WHERE institution_id=? ORDER BY code,academic_year DESC',(institution_id,))
@app.post('/api/courses')
async def create_course(request:Request,user=Depends(admin)):
    body=await request.json();iid=nint(body.get('institution_id'));assert_institution(iid)
    code=str(body.get('code','')).strip().upper().replace(' ','-')
    if not re.fullmatch(r'[A-Z]{2,5}-\d{3,4}[A-Z]?',code):fail('Course code must look like CIS-125')
    if body.get('source_url') and not str(body['source_url']).startswith('https://'):fail('Official source URL must be HTTPS')
    values=[str(body.get(k,'')).strip() for k in COURSE_FIELDS if k!='code']
    try:ident=execute('''INSERT INTO courses(institution_id,code,title,description,credits,prerequisites,academic_year,source_url,created_at) VALUES(?,?,?,?,?,?,?,?,?)''',(iid,code,*values,now()))
    except Exception:fail('Course with this code and academic year already exists',409)
    log(user['id'],'course.create',str(ident));return {'id':ident}
@app.put('/api/courses/{ident}')
async def update_course(ident:int,request:Request,user=Depends(admin)):
    old=one('SELECT * FROM courses WHERE id=?',(ident,))
    if not old:fail('Course not found',404)
    body=await request.json();values=pick(body,COURSE_FIELDS)
    if not values:fail('No changes supplied')
    if values.get('source_url') and not str(values['source_url']).startswith('https://'):fail('Official source URL must be HTTPS')
    if 'description' in values or 'source_url' in values:values['last_verified_at']=''
    values['version']=old['version']+1
    with transaction() as db:db.execute('UPDATE courses SET '+','.join(f'{k}=?' for k in values)+' WHERE id=?',(*values.values(),ident))
    record_revision('course',ident,old,values,user['id']);return {'ok':True}

@app.delete('/api/courses/all')
async def delete_all_courses(request:Request,user=Depends(admin)):
    """Destructive institution-scoped purge with explicit phrase and count check."""
    body=await request.json()
    institution_id=nint(body.get('institution_id'),'institution ID')
    assert_institution(institution_id)
    if body.get('confirmation')!='DELETE ALL':fail('Enter DELETE ALL to confirm removal.',400)
    try: expected_count=int(body.get('expected_count'))
    except (TypeError,ValueError):fail('Record count must be confirmed.',400)
    if expected_count<0:fail('Invalid record count.',400)
    with transaction() as db:
        running=db.execute("""SELECT id FROM catalog_imports WHERE institution_id=? AND status='running' LIMIT 1""",(institution_id,)).fetchone()
        if running:fail('A catalog import is still running. Wait for it to finish before deleting course records.',409)
        actual=db.execute('SELECT COUNT(*) FROM courses WHERE institution_id=?',(institution_id,)).fetchone()[0]
        if actual!=expected_count:
            fail(f'Course count changed from {expected_count} to {actual}. Refresh and review before deleting.',409)
        db.execute("DELETE FROM source_checks WHERE institution_id=? AND target_type='course'",(institution_id,))
        db.execute('DELETE FROM courses WHERE institution_id=?',(institution_id,))
    log(user['id'],'courses.delete_all',str(institution_id),f'{actual} course record(s) removed')
    return {'ok':True,'deleted':actual,'institution_id':institution_id}

@app.delete('/api/courses/{ident}')
def delete_course(ident:int,user=Depends(admin)):
    old=one('SELECT * FROM courses WHERE id=?',(ident,))
    if not old:fail('Course not found',404)
    with transaction() as db:
        db.execute("DELETE FROM source_checks WHERE institution_id=? AND target_type='course' AND target_id=?",
                   (old['institution_id'],ident))
        db.execute('DELETE FROM courses WHERE id=?',(ident,))
    record_revision('course.delete',ident,old,{'deleted':True},user['id'])
    log(user['id'],'course.delete',str(ident),old['code'])
    return {'ok':True}

@app.get('/api/source-checks')
def source_checks(institution_id:Optional[int]=None,user=Depends(current_user)):
    if institution_id:return all_rows('SELECT * FROM source_checks WHERE institution_id=? ORDER BY id DESC LIMIT 250',(institution_id,))
    return all_rows('SELECT * FROM source_checks ORDER BY id DESC LIMIT 250')
@app.post('/api/sources/check')
async def source_check(request:Request,user=Depends(admin)):
    body=await request.json();inst=assert_institution(body.get('institution_id'))
    result=await asyncio.to_thread(check_target,inst,body.get('target_type'),nint(body.get('target_id')))
    log(user['id'],'source.check',str(result['id']));return result
@app.post('/api/sources/discover')
async def source_discover(request:Request,user=Depends(admin)):
    body=await request.json();inst=assert_institution(body.get('institution_id'))
    code=str(body.get('code','')).strip().upper()
    if not re.fullmatch(r'[A-Z]{2,5}-\d{3,4}[A-Z]?',code):fail('Enter code such as CIS-125')
    return await asyncio.to_thread(discover_course,inst,code,20)
@app.post('/api/sources/refresh')
async def source_refresh(request:Request,user=Depends(admin)):
    body=await request.json();inst=assert_institution(body.get('institution_id'))
    return {'checks':await asyncio.to_thread(refresh_institution,inst)}
@app.post('/api/sources/{ident}/approve')
async def source_approve(ident:int,request:Request,user=Depends(admin)):
    row=one('SELECT * FROM source_checks WHERE id=?',(ident,))
    if not row:fail('Source check not found',404)
    if row['approved_at']:fail('Already reviewed')
    if row['status'] not in ('changed','needs_review'):fail('Source check has no proposed update')
    body=await request.json();approved_text=str(body.get('approved_text','')).strip()
    if not approved_text:fail('Enter verified source text before approving')
    table='courses' if row['target_type']=='course' else 'requirements'
    target=one(f'SELECT * FROM {table} WHERE id=? AND institution_id=?',(row['target_id'],row['institution_id']))
    if not target:fail('Target no longer exists',404)
    field='description' if row['target_type']=='course' else 'expected_text'
    updated={field:approved_text,'version':target['version']+1}
    if table=='courses':updated['last_verified_at']=now()
    else:updated['updated_at']=now()
    with transaction() as db:
        db.execute(f'UPDATE {table} SET '+','.join(f'{k}=?' for k in updated)+' WHERE id=?',(*updated.values(),target['id']))
        db.execute('UPDATE source_checks SET approved_at=? WHERE id=?',(now(),ident))
    record_revision(row['target_type'],target['id'],target,updated,user['id'])
    log(user['id'],'source.approve',str(ident));return {'ok':True}

@app.post('/api/audits/upload')
async def upload_audits(request:Request, institution_id:int=Form(...),template_id:Optional[int]=Form(None),academic_year:str=Form(''),
                        files:list[UploadFile]=File(...),user=Depends(current_user)):
    inst=assert_institution(institution_id)
    if template_id is None:
        default=one('SELECT id FROM templates WHERE institution_id=? AND active=1 AND is_default=1',(institution_id,))
        template_id=default['id'] if default else 0
    if template_id:
        chosen=assert_template(template_id,institution_id)
        if not chosen['active']:fail('Selected template is inactive')
    if not files or len(files)>100:fail('Upload between 1 and 100 files')
    if len(academic_year)>40:fail('Academic year is too long')
    # All validation occurs before anything is created.
    staged=[]
    for f in files:
        content=await f.read(MAX_UPLOAD+1)
        suffix=validate_upload(f.filename,content)
        staged.append((Path(f.filename).name[:180],suffix,content))
        if sum(len(row[2]) for row in staged)>200*1024*1024:fail('Combined batch upload exceeds 200 MB')
    job_id=execute('INSERT INTO audit_jobs(institution_id,template_id,academic_year,created_by,created_at,total) VALUES(?,?,?,?,?,?)',
      (institution_id,template_id or None,academic_year,user['id'],now(),len(staged)))
    audit_ids=[]
    for filename,suffix,content in staged:
        path=UPLOAD_DIR/(secrets.token_hex(20)+suffix)
        path.write_bytes(content)
        ident=execute('''INSERT INTO audits(job_id,institution_id,template_id,filename,storage_path,filetype,academic_year,created_at,created_by) VALUES(?,?,?,?,?,?,?,?,?)''',
        (job_id,institution_id,template_id or None,filename,str(path),suffix,academic_year,now(),user['id']))
        # Keep the original audit ID as the stable syllabus record identity.
        execute('UPDATE audits SET series_id=? WHERE id=?',(ident,ident))
        audit_ids.append(ident)
    executor.submit(run_job,job_id)
    log(user['id'],'audits.upload',str(job_id),f'{len(audit_ids)} file(s)')
    return {'job_id':job_id,'audit_ids':audit_ids,'status':'queued'}
@app.get('/api/jobs')
def jobs(user=Depends(current_user)):
    return all_rows('''SELECT j.*,i.name AS institution_name FROM audit_jobs j JOIN institutions i ON i.id=j.institution_id
            WHERE EXISTS (SELECT 1 FROM audits a WHERE a.job_id=j.id AND a.rerun_of_id IS NULL)
            ORDER BY j.id DESC LIMIT 100''')
@app.get('/api/jobs/{ident}')
def job_status(ident:int,user=Depends(current_user)):
    job=one('SELECT * FROM audit_jobs WHERE id=?',(ident,))
    if not job:fail('Job not found',404)
    return {'job':job,'audits':all_rows('SELECT id,filename,course_code,status,passed,warnings,failed,review,error FROM audits WHERE job_id=? ORDER BY id',(ident,))}
@app.post('/api/jobs/{ident}/retry')
def retry_job(ident:int,user=Depends(current_user)):
    job=one('SELECT * FROM audit_jobs WHERE id=?',(ident,))
    if not job:fail('Job not found',404)
    if job['status'] not in ('interrupted','complete_with_errors'):fail('Only interrupted or errored jobs may be retried')
    failures=all_rows('SELECT id FROM audits WHERE job_id=? AND status IN ("interrupted","error")',(ident,))
    if not failures:fail('No failed uploads to retry')
    with transaction() as db:
        db.execute('UPDATE audit_jobs SET status="queued",total=?,finished=0,error="" WHERE id=?',(len(failures),ident))
        for row in failures:db.execute('UPDATE audits SET status="queued",error="" WHERE id=?',(row['id'],))
    executor.submit(run_job,ident)
    return {'ok':True}
def _may_manage_audit(audit, user):
    """Only the report owner or an administrator may mutate a saved audit."""
    if audit['created_by']!=user['id'] and user['role']!='admin':
        fail('Only the report owner or an administrator can change this report',403)


def _saved_document_path(audit):
    """Refuse to open arbitrary database-backed paths outside protected uploads."""
    path=Path(audit['storage_path']).resolve()
    if not path.is_relative_to(UPLOAD_DIR.resolve()):
        fail('Saved syllabus path is outside application storage',409)
    return path


@app.post('/api/audits/{ident}/rerun')
def rerun_audit(ident:int,user=Depends(current_user)):
    """Create a new immutable revision in the same syllabus series."""
    requested=one('SELECT * FROM audits WHERE id=?',(ident,))
    if not requested:fail('Audit not found',404)
    _may_manage_audit(requested,user)
    series_id=requested['series_id'] or requested['id']
    original=one('SELECT * FROM audits WHERE COALESCE(series_id,id)=? ORDER BY id DESC LIMIT 1',(series_id,))
    if original['status'] not in ('complete','error','interrupted'):
        fail('Wait for the current syllabus check to finish before rerunning',409)
    source=_saved_document_path(original)
    if not source.is_file():fail('Original syllabus is no longer stored. Upload it again to rerun checks.',409)
    template_id=original['template_id']
    if template_id is None:
        default=one('SELECT id FROM templates WHERE institution_id=? AND active=1 AND is_default=1',(original['institution_id'],))
        template_id=default['id'] if default else None
    destination=UPLOAD_DIR/(secrets.token_hex(20)+original['filetype'])
    # Each revision preserves its own source and review evidence for comparison.
    try:
        shutil.copyfile(source,destination)
        with transaction() as db:
            cur=db.execute("""INSERT INTO audit_jobs(institution_id,template_id,academic_year,created_by,created_at,total)
                              VALUES(?,?,?,?,?,1)""",
                (original['institution_id'],template_id,original['academic_year'],user['id'],now()))
            job_id=cur.lastrowid
            # Guard against two simultaneous reruns of the same syllabus series.
            latest=db.execute('SELECT id,status FROM audits WHERE COALESCE(series_id,id)=? ORDER BY id DESC LIMIT 1',(series_id,)).fetchone()
            if not latest or latest['id']!=original['id'] or latest['status'] in ('queued','running'):
                fail('Another check has already started for this syllabus',409)
            cur=db.execute("""INSERT INTO audits(job_id,rerun_of_id,series_id,institution_id,template_id,filename,
                              storage_path,filetype,academic_year,created_at,created_by)
                              VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (job_id,original['id'],series_id,original['institution_id'],template_id,
                 original['filename'],str(destination),original['filetype'],original['academic_year'],now(),user['id']))
            new_id=cur.lastrowid
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    executor.submit(run_job,job_id)
    log(user['id'],'audit.rerun',str(new_id),f'from #{ident}')
    return {'ok':True,'job_id':job_id,'audit_id':new_id,'series_id':series_id,'rerun_of_id':original['id'],'status':'queued'}


@app.delete('/api/audits/{ident}')
def delete_audit(ident:int,user=Depends(current_user)):
    """Delete one finished report, its findings and its private saved source file."""
    audit=one('SELECT * FROM audits WHERE id=?',(ident,))
    if not audit:fail('Audit not found',404)
    _may_manage_audit(audit,user)
    if audit['status'] in ('queued','running'):
        fail('Cannot delete a report while its check is running',409)
    job=one('SELECT status FROM audit_jobs WHERE id=?',(audit['job_id'],)) if audit['job_id'] else None
    if job and job['status'] in ('queued','running'):
        fail('Cannot delete reports from a batch that is still running',409)
    source=_saved_document_path(audit)
    approved=Path(audit['approved_path']).resolve() if audit.get('approved_path') else None
    if approved and not approved.is_relative_to(UPLOAD_DIR.resolve()):
        fail('Approved document path is outside application storage',409)
    shared=one('SELECT id FROM audits WHERE storage_path=? AND id!=? LIMIT 1',(audit['storage_path'],ident))
    # Renaming first avoids reporting success when Windows is unable to release an open file.
    staged=None
    if source.exists() and not shared:
        if not source.is_file():fail('Stored document is not a regular file',409)
        staged=UPLOAD_DIR/('.deleting-'+secrets.token_hex(16))
        try:source.rename(staged)
        except OSError:fail('Unable to remove stored syllabus. Close open downloads and try again.',409)
    try:
        with transaction() as db:
            db.execute('DELETE FROM audits WHERE id=?',(ident,))
            if audit['job_id']:
                count=db.execute('SELECT COUNT(*) FROM audits WHERE job_id=?',(audit['job_id'],)).fetchone()[0]
                if count==0:
                    db.execute('DELETE FROM audit_jobs WHERE id=?',(audit['job_id'],))
                else:
                    problems=db.execute('SELECT COUNT(*) FROM audits WHERE job_id=? AND status IN ("error","interrupted")',(audit['job_id'],)).fetchone()[0]
                    db.execute('UPDATE audit_jobs SET total=?,finished=?,status=? WHERE id=?',
                        (count,count,'complete_with_errors' if problems else 'complete',audit['job_id']))
    except Exception:
        if staged and staged.exists():staged.rename(source)
        raise
    file_removed=True
    if staged:
        try:staged.unlink()
        except OSError:file_removed=False
    if approved and approved.exists():
        try:approved.unlink()
        except OSError:file_removed=False
    log(user['id'],'audit.delete',str(ident),'Report and stored syllabus deletion requested')
    return {'ok':True,'deleted_audit_id':ident,'stored_file_removed':file_removed}


@app.get('/api/audits')
def audits(institution_id:Optional[int]=None,limit:int=200,user=Depends(current_user)):
    limit=max(1,min(500,limit))
    query='''SELECT a.*,
             (SELECT COUNT(*) FROM findings f WHERE f.audit_id=a.id AND f.status!='passed' AND f.accepted=0 AND f.dismissed=0) AS pending_findings,
             (SELECT COUNT(*) FROM findings f WHERE f.audit_id=a.id AND f.status!='passed' AND (f.accepted=1 OR f.dismissed=1)) AS reviewed_findings,
             (SELECT COUNT(*) FROM audits v WHERE COALESCE(v.series_id,v.id)=COALESCE(a.series_id,a.id)) AS revision_count
             FROM audits a'''
    if institution_id:
        return all_rows(query+' WHERE a.institution_id=? AND a.id=(SELECT MAX(z.id) FROM audits z WHERE COALESCE(z.series_id,z.id)=COALESCE(a.series_id,a.id)) ORDER BY a.id DESC LIMIT ?', (institution_id,limit))
    return all_rows(query+' WHERE a.id=(SELECT MAX(z.id) FROM audits z WHERE COALESCE(z.series_id,z.id)=COALESCE(a.series_id,a.id)) ORDER BY a.id DESC LIMIT ?',(limit,))
@app.get('/api/audits/export.csv')
def export_csv(user=Depends(current_user)):
    data=csv_report(all_rows('''SELECT * FROM audits a WHERE a.id=(SELECT MAX(z.id) FROM audits z WHERE COALESCE(z.series_id,z.id)=COALESCE(a.series_id,a.id)) ORDER BY a.id DESC LIMIT 10000'''))
    return Response(data,media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="syllabus-audit-summary.csv"'})
@app.get('/api/audit-series/{series_id}')
def current_syllabus_revision(series_id:int,user=Depends(current_user)):
    latest=one('SELECT id,series_id FROM audits WHERE COALESCE(series_id,id)=? ORDER BY id DESC LIMIT 1',(series_id,))
    if not latest:fail('Syllabus record not found',404)
    return {'series_id':series_id,'audit_id':latest['id']}

@app.get('/api/audits/{ident}/history')
def audit_revision_history(ident:int,user=Depends(current_user)):
    selected=one('SELECT id,series_id FROM audits WHERE id=?',(ident,))
    if not selected:fail('Audit not found',404)
    series_id=selected['series_id'] or selected['id']
    rows=all_rows('''SELECT a.id,a.series_id,a.rerun_of_id,a.status,a.created_at,a.completed_at,
                            a.passed,a.warnings,a.failed,a.review,a.approved_at,a.error,
                            a.created_by,u.username AS checked_by,
                            (SELECT COUNT(*) FROM findings f WHERE f.audit_id=a.id AND f.status!='passed' AND f.accepted=0 AND f.dismissed=0) AS pending_findings
                     FROM audits a LEFT JOIN users u ON u.id=a.created_by
                     WHERE COALESCE(a.series_id,a.id)=? ORDER BY a.id DESC''',(series_id,))
    for ix,row in enumerate(reversed(rows),1):row['revision_number']=ix
    return {'series_id':series_id,'current_audit_id':rows[0]['id'],'selected_audit_id':ident,'revisions':rows}

@app.delete('/api/audit-series/{series_id}')
def delete_syllabus_series(series_id:int,user=Depends(current_user)):
    # Delete the syllabus record and every revision, only after all jobs finish.
    rows=all_rows('SELECT * FROM audits WHERE COALESCE(series_id,id)=? ORDER BY id',(series_id,))
    if not rows:fail('Syllabus record not found',404)
    _may_manage_audit(rows[0],user)
    if any(a['status'] in ('queued','running') for a in rows):
        fail('Cannot delete a syllabus while a check is running',409)
    for job_id in {a['job_id'] for a in rows if a['job_id']}:
        job=one('SELECT status FROM audit_jobs WHERE id=?',(job_id,))
        if job and job['status'] in ('queued','running'):
            fail('Cannot delete reports from an active batch',409)
    # Stage files for removal; roll back renames if database deletion fails.
    staged=[]
    try:
        destinations=set()
        for row in rows:
            destinations.add(_saved_document_path(row))
            if row['approved_path']:
                approved=Path(row['approved_path']).resolve()
                if not approved.is_relative_to(UPLOAD_DIR.resolve()):fail('Approved document path is invalid',409)
                destinations.add(approved)
        for path in destinations:
            # Never remove a file shared with a different syllabus series.
            external=one('''SELECT id FROM audits WHERE COALESCE(series_id,id)!=? AND (storage_path=? OR approved_path=?) LIMIT 1''',
                         (series_id,str(path),str(path)))
            if external or not path.exists():continue
            if not path.is_file():fail('Saved syllabus path is not a file',409)
            hidden=UPLOAD_DIR/('.deleting-'+secrets.token_hex(16))
            path.rename(hidden)
            staged.append((path,hidden))
        with transaction() as db:
            # Recheck that no new revision was queued while files were staged.
            latest_ids=[r['id'] for r in db.execute('SELECT id FROM audits WHERE COALESCE(series_id,id)=? ORDER BY id',(series_id,))]
            if latest_ids!=[r['id'] for r in rows]:fail('Syllabus changed while deleting; retry',409)
            db.execute('DELETE FROM audits WHERE COALESCE(series_id,id)=?',(series_id,))
            for job_id in {a['job_id'] for a in rows if a['job_id']}:
                others=list(db.execute('SELECT status FROM audits WHERE job_id=?',(job_id,)))
                if not others: db.execute('DELETE FROM audit_jobs WHERE id=?',(job_id,))
                else:
                    problems=any(a['status'] in ('error','interrupted') for a in others)
                    db.execute('UPDATE audit_jobs SET total=?,finished=?,status=? WHERE id=?',
                               (len(others),len(others),'complete_with_errors' if problems else 'complete',job_id))
    except Exception:
        for old,hidden in reversed(staged):
            if hidden.exists():hidden.rename(old)
        raise
    removed=True
    for old,hidden in staged:
        try:hidden.unlink()
        except OSError:removed=False
    log(user['id'],'syllabus.delete',str(series_id),f'Removed {len(rows)} revision(s)')
    return {'ok':True,'series_id':series_id,'revisions_deleted':len(rows),'stored_files_removed':removed}

@app.get('/api/audits/{ident}')
def audit_detail(ident:int,user=Depends(current_user)):
    a,findings=load(ident)
    if not a:fail('Audit not found',404)
    return {'audit':a,'findings':findings,'review_summary':review_summary(findings)}
@app.get('/api/audits/{ident}/document')
def audit_file(ident:int,user=Depends(current_user)):
    a=one('SELECT filename,storage_path,filetype FROM audits WHERE id=?',(ident,))
    if not a:fail('Audit not found',404)
    if not Path(a['storage_path']).is_file():fail('Document missing',404)
    return FileResponse(a['storage_path'],filename=a['filename'],media_type='application/pdf' if a['filetype']=='.pdf' else None,
         content_disposition_type='inline' if a['filetype']=='.pdf' else 'attachment')
@app.get('/api/audits/{ident}/report.{fmt}')
def report(ident:int,fmt:str,user=Depends(current_user)):
    a,findings=load(ident)
    if not a:fail('Audit not found',404)
    if a['status']!='complete':fail('Audit is not finished')
    if fmt=='pdf':data=pdf_report(a,findings);mime='application/pdf'
    elif fmt=='docx':data=docx_report(a,findings);mime='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    else:fail('Supported report types: pdf, docx')
    return Response(data,media_type=mime,headers={'Content-Disposition':f'attachment; filename="audit-{ident}.{fmt}"'})
@app.get('/api/jobs/{ident}/export.zip')
def batch_download(ident:int,user=Depends(current_user)):
    if not one('SELECT id FROM audit_jobs WHERE id=?',(ident,)):fail('Job not found',404)
    return Response(batch_zip(ident),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="audit-batch-{ident}.zip"'})
@app.put('/api/findings/{ident}')
async def edit_finding(ident:int,request:Request,user=Depends(current_user)):
    original=one('SELECT * FROM findings WHERE id=?',(ident,))
    if not original:fail('Finding not found',404)
    audit=one('SELECT * FROM audits WHERE id=?',(original['audit_id'],))
    if not audit:fail('Audit not found',404)
    _may_manage_audit(audit,user)
    if audit['status']!='complete':fail('Review is available only after the audit finishes',409)
    if one('SELECT MAX(id) AS id FROM audits WHERE COALESCE(series_id,id)=?',(audit['series_id'] or audit['id'],))['id']!=audit['id']:
        fail('This is an archived check. Review the latest syllabus revision instead.',409)
    if audit['approved_at']:fail('Approved syllabi are locked. Rerun the audit to review new decisions.',409)
    if original['status']=='passed':fail('Passing findings do not need review',409)
    body=await request.json()
    if not isinstance(body,dict) or not any(k in body for k in ('accepted','dismissed')):
        fail('Only review fields can be updated')
    if any(k not in ('accepted','dismissed') for k in body):fail('Invalid review field')
    if any(not isinstance(x,bool) for x in body.values()):fail('Review decisions must be booleans')
    accepted=int(bool(body.get('accepted',original['accepted'])))
    dismissed=int(bool(body.get('dismissed',original['dismissed'])))
    if accepted and dismissed:fail('Cannot both accept and dismiss')
    with transaction() as db:
        # Revalidate approval in the same transaction as the mutation.
        row=db.execute('SELECT approved_at FROM audits WHERE id=?',(audit['id'],)).fetchone()
        if not row or row['approved_at']:fail('Approved syllabus reviews are locked',409)
        db.execute('UPDATE findings SET accepted=?,dismissed=?,reviewed_by=?,reviewed_at=? WHERE id=?',
                   (accepted,dismissed,user['id'] if accepted or dismissed else None,now() if accepted or dismissed else '',ident))
        refreshed=[dict(r) for r in db.execute('SELECT * FROM findings WHERE audit_id=?',(audit['id'],))]
    summary=review_summary(refreshed)
    log(user['id'],'finding.review',str(ident),json.dumps({'accepted':accepted,'dismissed':dismissed}))
    return {'ok':True,'review_summary':summary}
@app.post('/api/audits/{ident}/approve')
def approve_audit(ident:int,user=Depends(current_user)):
    audit=one('SELECT * FROM audits WHERE id=?',(ident,))
    if not audit:fail('Audit not found',404)
    _may_manage_audit(audit,user)
    if audit['status']!='complete':fail('Finish the audit before approving the syllabus',409)
    if one('SELECT MAX(id) AS id FROM audits WHERE COALESCE(series_id,id)=?',(audit['series_id'] or audit['id'],))['id']!=audit['id']:
        fail('Only the latest syllabus check can be approved',409)
    if audit['approved_at']:fail('This syllabus is already approved; rerun to create a new approval',409)
    source=_saved_document_path(audit)
    if not source.is_file():fail('The saved syllabus is missing',409)
    destination=UPLOAD_DIR/(secrets.token_hex(20)+audit['filetype'])
    approved_time=now()
    try:
        with transaction() as db:
            row=db.execute('SELECT approved_at FROM audits WHERE id=?',(ident,)).fetchone()
            if not row or row['approved_at']:fail('This syllabus is already approved',409)
            findings=[dict(x) for x in db.execute('SELECT * FROM findings WHERE audit_id=? ORDER BY id',(ident,))]
            summary=review_summary(findings)
            if summary['remaining']:
                fail(f"Review all {summary['remaining']} remaining finding(s) before approving",409)
            snapshot={'approved_by':user['username'],'approved_at':approved_time,
                      'source_filename':audit['filename'],'audit_id':ident,
                      'summary':summary,
                      'decisions':[{'id':f['id'],'title':f['title'],'status':f['status'],
                                    'decision':'accepted' if f['accepted'] else 'dismissed' if f['dismissed'] else 'passed',
                                    'observed':f['observed'],'expected':f['expected']}
                                   for f in findings]}
            data=build_approved_syllabus(source,audit['filetype'],findings,snapshot)
            destination.write_bytes(data)
            db.execute('UPDATE audits SET approved_at=?,approved_by=?,approved_path=?,approval_snapshot=? WHERE id=?',
                       (approved_time,user['id'],str(destination),json.dumps(snapshot),ident))
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    log(user['id'],'audit.approve',str(ident),f"Accepted {summary['accepted']}; waived {summary['dismissed']}")
    return {'ok':True,'approved_at':approved_time,'review_summary':summary,'download_url':f'/api/audits/{ident}/approved'}

@app.get('/api/audits/{ident}/approved')
def approved_syllabus(ident:int,user=Depends(current_user)):
    audit=one('SELECT * FROM audits WHERE id=?',(ident,))
    if not audit:fail('Audit not found',404)
    if not audit['approved_at'] or not audit['approved_path']:fail('This syllabus has not been approved',409)
    artifact=Path(audit['approved_path']).resolve()
    if not artifact.is_relative_to(UPLOAD_DIR.resolve()):fail('Approved document path is invalid',409)
    if not artifact.is_file():fail('Approved document is missing',404)
    filename=Path(audit['filename']).stem[:120]+'-approved'+audit['filetype']
    return FileResponse(artifact,filename=filename,content_disposition_type='attachment')

@app.get('/api/audits/{ident}/corrected.docx')
def corrected_docx(ident:int,user=Depends(current_user)):
    a,findings=load(ident)
    if not a:fail('Audit not found',404)
    if a['filetype']!='.docx':fail('Corrected copies are supported for DOCX input only')
    corrections=[(f['id'],f['observed'],f['expected']) for f in findings if f['accepted'] and not f['dismissed'] and f['status']!='passed']
    if not corrections:fail('Accept at least one applicable correction before exporting')
    data,applied,skipped=correct_docx(a['storage_path'],corrections)
    if not applied:fail('Selected corrections could not be applied safely to document paragraphs. Download the report for manual editing.')
    return Response(data,media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      headers={'Content-Disposition':f'attachment; filename="corrected-{ident}.docx"',
               'X-Corrections-Applied':','.join(map(str,applied)),'X-Corrections-Skipped':','.join(map(str,skipped))})
@app.get('/api/audits/{ident}/compare')
def compare_audit(ident:int,user=Depends(current_user)):
    a=one('SELECT * FROM audits WHERE id=?',(ident,))
    if not a:fail('Audit not found',404)
    old=(one('SELECT id FROM audits WHERE id=?',(a['rerun_of_id'],)) if a.get('rerun_of_id') else None)
    if not old:old=one('SELECT id FROM audits WHERE id<? AND institution_id=? AND course_code=? AND course_code!="" ORDER BY id DESC LIMIT 1',(ident,a['institution_id'],a['course_code']))
    previous=all_rows('SELECT code,status,title FROM findings WHERE audit_id=?',(old['id'],)) if old else []
    latest=all_rows('SELECT code,status,title FROM findings WHERE audit_id=?',(ident,))
    by_code={r['code']:r for r in previous}
    changes=[{'code':r['code'],'title':r['title'],'current':r['status'],'previous':by_code.get(r['code'],{}).get('status','new')} for r in latest if by_code.get(r['code'],{}).get('status')!=r['status']]
    return {'previous_audit_id':old['id'] if old else None,'changes':changes}

@app.get('/api/activity')
def activity(user=Depends(admin)):
    return all_rows('SELECT a.*,u.username FROM activity a LEFT JOIN users u ON u.id=a.actor_id ORDER BY a.id DESC LIMIT 250')
@app.get('/api/revisions')
def revisions(kind:str='',user=Depends(admin)):
    return all_rows('SELECT * FROM revisions WHERE kind=? ORDER BY id DESC LIMIT 200',(kind,)) if kind else all_rows('SELECT * FROM revisions ORDER BY id DESC LIMIT 200')
@app.get('/api/users')
def users(user=Depends(admin)):
    return all_rows('SELECT id,username,role,created_at FROM users WHERE username!=? ORDER BY username',(desktop_auth.DESKTOP_USER,))
@app.post('/api/users')
async def add_user(request:Request,user=Depends(admin)):
    body=await request.json();username=str(body.get('username','')).strip().lower();pwd=str(body.get('password',''))
    role=body.get('role','reviewer')
    if username==desktop_auth.DESKTOP_USER:fail('This username is reserved',400)
    if role not in ('admin','reviewer'):fail('Invalid role')
    if not re.fullmatch(r'[a-z0-9._-]{3,40}',username) or len(pwd)<12:fail('Username invalid or password shorter than 12 characters')
    try:ident=execute('INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,?,?)',(username,pbkdf(pwd),role,now()))
    except Exception:fail('Username already exists',409)
    log(user['id'],'user.create',str(ident));return {'id':ident}
@app.post('/api/users/password')
async def change_password(request:Request,user=Depends(current_user)):
    if desktop_auth.ENABLED and user['username']==desktop_auth.DESKTOP_USER and not desktop_auth.password_required():
        fail('Enable startup password protection in Desktop Security first',403)
    body=await request.json();record=one('SELECT * FROM users WHERE id=?',(user['id'],))
    if not valid_password(str(body.get('old_password','')),record['password_hash']):fail('Current password incorrect')
    pwd=str(body.get('new_password',''))
    if len(pwd)<12:fail('New password must be at least 12 characters')
    execute('UPDATE users SET password_hash=? WHERE id=?',(pbkdf(pwd),user['id']))
    execute('DELETE FROM sessions WHERE user_id=? AND token_hash!=?',(user['id'],token_hash(request.cookies.get('sa_session',''))))
    return {'ok':True}
@app.get('/api/runtime')
def runtime(user=Depends(current_user)):
    return {'ai':ai.status(),'model_path':str(MODEL_PATH),'data_path':str(DATA_DIR),'max_upload_mb':MAX_UPLOAD//1024//1024,
            'monitor_interval_hours':MONITOR_INTERVAL_HOURS,'ai_external_connections':False,
            'desktop_mode':desktop_auth.ENABLED,
            'desktop_password_required':desktop_auth.password_required() if desktop_auth.ENABLED else False}
