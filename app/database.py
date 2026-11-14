import sqlite3, json, threading
from datetime import datetime, timezone
from contextlib import contextmanager
from .config import DB_PATH
SCHEMA = '''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
 role TEXT NOT NULL DEFAULT 'reviewer', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 csrf TEXT NOT NULL, expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS institutions (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, short_name TEXT DEFAULT '',
 catalog_url TEXT DEFAULT '', catalog_url_pattern TEXT DEFAULT '', allowed_hosts TEXT DEFAULT '',
 academic_year TEXT DEFAULT '', active INTEGER DEFAULT 1, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS templates (
 id INTEGER PRIMARY KEY, institution_id INTEGER NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
 name TEXT NOT NULL, academic_year TEXT DEFAULT '', version INTEGER NOT NULL DEFAULT 1,
 notes TEXT DEFAULT '', doc_path TEXT DEFAULT '', sections_json TEXT NOT NULL DEFAULT '[]',
 active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS requirements (
 id INTEGER PRIMARY KEY, institution_id INTEGER NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
 template_id INTEGER REFERENCES templates(id) ON DELETE SET NULL, name TEXT NOT NULL,
 category TEXT NOT NULL DEFAULT 'policy', mode TEXT NOT NULL DEFAULT 'exact',
 severity TEXT NOT NULL DEFAULT 'critical', expected_text TEXT NOT NULL DEFAULT '',
 variants_json TEXT NOT NULL DEFAULT '[]', keywords TEXT NOT NULL DEFAULT '',
 source_url TEXT NOT NULL DEFAULT '', effective_from TEXT NOT NULL DEFAULT '',
 effective_to TEXT NOT NULL DEFAULT '', department TEXT NOT NULL DEFAULT '',
 active INTEGER NOT NULL DEFAULT 1, version INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS courses (
 id INTEGER PRIMARY KEY, institution_id INTEGER NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
 code TEXT NOT NULL, title TEXT DEFAULT '', description TEXT DEFAULT '',
 credits TEXT DEFAULT '', prerequisites TEXT DEFAULT '', academic_year TEXT DEFAULT '',
 source_url TEXT DEFAULT '', version INTEGER NOT NULL DEFAULT 1,
 last_verified_at TEXT DEFAULT '', created_at TEXT NOT NULL,
 UNIQUE(institution_id, code, academic_year));
CREATE TABLE IF NOT EXISTS catalog_imports (
 id INTEGER PRIMARY KEY, institution_id INTEGER NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
 created_by INTEGER NOT NULL REFERENCES users(id), seed_url TEXT NOT NULL, subject_codes TEXT DEFAULT '', academic_year TEXT DEFAULT '',
 status TEXT NOT NULL DEFAULT 'running', max_pages INTEGER NOT NULL DEFAULT 350,
 pages_scanned INTEGER NOT NULL DEFAULT 0, courses_found INTEGER NOT NULL DEFAULT 0,
 truncated INTEGER NOT NULL DEFAULT 0, errors_json TEXT DEFAULT '[]', error TEXT DEFAULT '',
 created_at TEXT NOT NULL, finished_at TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS catalog_import_items (
 id INTEGER PRIMARY KEY, import_id INTEGER NOT NULL REFERENCES catalog_imports(id) ON DELETE CASCADE,
 code TEXT NOT NULL, title TEXT DEFAULT '', description TEXT DEFAULT '', credits TEXT DEFAULT '',
 prerequisites TEXT DEFAULT '', source_url TEXT DEFAULT '', evidence TEXT DEFAULT '', status TEXT DEFAULT '',
 UNIQUE(import_id,code));
CREATE INDEX IF NOT EXISTS idx_catalog_imports_inst ON catalog_imports(institution_id);
CREATE TABLE IF NOT EXISTS source_checks (
 id INTEGER PRIMARY KEY, institution_id INTEGER NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
 target_type TEXT NOT NULL, target_id INTEGER NOT NULL, url TEXT NOT NULL,
 checked_at TEXT NOT NULL, status TEXT NOT NULL, old_text TEXT DEFAULT '', new_text TEXT DEFAULT '',
 evidence TEXT DEFAULT '', error TEXT DEFAULT '', approved_at TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS audit_jobs (
 id INTEGER PRIMARY KEY, institution_id INTEGER NOT NULL REFERENCES institutions(id),
 template_id INTEGER REFERENCES templates(id), academic_year TEXT DEFAULT '',
 status TEXT NOT NULL DEFAULT 'queued', created_by INTEGER NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL, finished_at TEXT DEFAULT '', error TEXT DEFAULT '',
 total INTEGER DEFAULT 0, finished INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS audits (
 id INTEGER PRIMARY KEY, job_id INTEGER REFERENCES audit_jobs(id) ON DELETE SET NULL,
 rerun_of_id INTEGER REFERENCES audits(id) ON DELETE SET NULL,
 institution_id INTEGER NOT NULL REFERENCES institutions(id), template_id INTEGER REFERENCES templates(id),
 filename TEXT NOT NULL, storage_path TEXT NOT NULL, filetype TEXT NOT NULL,
 course_code TEXT DEFAULT '', academic_year TEXT DEFAULT '',
 status TEXT DEFAULT 'queued', passed INTEGER DEFAULT 0, warnings INTEGER DEFAULT 0,
 failed INTEGER DEFAULT 0, review INTEGER DEFAULT 0, extraction_text TEXT DEFAULT '',
 extraction_json TEXT DEFAULT '[]', created_at TEXT NOT NULL, completed_at TEXT DEFAULT '',
 error TEXT DEFAULT '', created_by INTEGER NOT NULL REFERENCES users(id));
CREATE TABLE IF NOT EXISTS findings (
 id INTEGER PRIMARY KEY, audit_id INTEGER NOT NULL REFERENCES audits(id) ON DELETE CASCADE,
 requirement_id INTEGER REFERENCES requirements(id) ON DELETE SET NULL, code TEXT DEFAULT '',
 title TEXT NOT NULL, category TEXT NOT NULL, status TEXT NOT NULL,
 severity TEXT DEFAULT '', observed TEXT DEFAULT '', expected TEXT DEFAULT '',
 explanation TEXT DEFAULT '', source_url TEXT DEFAULT '', location TEXT DEFAULT '',
 confidence REAL DEFAULT 0, evidence_json TEXT DEFAULT '{}',
 accepted INTEGER DEFAULT 0, dismissed INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS revisions (
 id INTEGER PRIMARY KEY, kind TEXT NOT NULL, target_id INTEGER NOT NULL, actor_id INTEGER,
 old_json TEXT DEFAULT '{}', new_json TEXT DEFAULT '{}', changed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS activity (
 id INTEGER PRIMARY KEY, actor_id INTEGER, verb TEXT NOT NULL, target TEXT DEFAULT '',
 detail TEXT DEFAULT '', created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_audits_created ON audits(created_at);
CREATE INDEX IF NOT EXISTS idx_findings_audit ON findings(audit_id);
CREATE INDEX IF NOT EXISTS idx_requirements_inst ON requirements(institution_id);
CREATE INDEX IF NOT EXISTS idx_courses_inst ON courses(institution_id);
'''
_db_lock = threading.RLock()
def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def connect():
    db = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=30000')
    return db

def initialize():
    with _db_lock, connect() as db:
        db.executescript(SCHEMA)
        if 'rerun_of_id' not in {c[1] for c in db.execute('PRAGMA table_info(audits)').fetchall()}:
            db.execute("ALTER TABLE audits ADD COLUMN rerun_of_id INTEGER REFERENCES audits(id) ON DELETE SET NULL")
        if 'subject_codes' not in {c[1] for c in db.execute('PRAGMA table_info(catalog_imports)').fetchall()}:
            db.execute("ALTER TABLE catalog_imports ADD COLUMN subject_codes TEXT DEFAULT ''")
        db.execute("UPDATE catalog_imports SET status='interrupted',error='Application restarted during scan' WHERE status='running'")
        db.execute("UPDATE audit_jobs SET status='interrupted', error='Application restarted before completion' WHERE status IN ('running','queued')")
        db.execute("UPDATE audits SET status='interrupted', error='Application restarted before completion' WHERE status IN ('running','queued')")
        db.commit()

@contextmanager
def transaction():
    with _db_lock:
        db=connect()
        try:
            yield db
            db.commit()
        except:
            db.rollback()
            raise
        finally:
            db.close()

def all_rows(sql, params=()):
    with connect() as db: return [dict(x) for x in db.execute(sql,params).fetchall()]
def one(sql, params=()):
    with connect() as db:
        x=db.execute(sql,params).fetchone()
        return dict(x) if x is not None else None

def execute(sql,params=()):
    with transaction() as db:
        cur=db.execute(sql,params)
        return cur.lastrowid

def record_revision(kind, ident, before, after, actor_id=None):
    execute('INSERT INTO revisions(kind,target_id,actor_id,old_json,new_json,changed_at) VALUES (?,?,?,?,?,?)',
    (kind,ident,actor_id,json.dumps(before,default=str),json.dumps(after,default=str),now()))

def log(actor,verb,target='',detail=''):
    execute('INSERT INTO activity(actor_id,verb,target,detail,created_at) VALUES (?,?,?,?,?)', (actor,verb,target,detail,now()))
