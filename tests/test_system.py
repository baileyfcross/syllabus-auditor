"""Offline integration tests, no network connections or AI model required."""
import io, os, time, secrets
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from docx import Document

# Configured before the application modules are imported.
import tempfile
_test_data=tempfile.mkdtemp(prefix='sa-test-')
os.environ['SA_DATA_DIR']=_test_data
from app import main
from app.database import one,execute,all_rows
from app.documents import extract,template_sections,infer_course_code
from app.validation import audit_document, candidate_segments
from app.sources import validate_url,check_target

@pytest.fixture(scope='module')
def client():
    with TestClient(main.app) as c:
        token=(Path(_test_data)/'bootstrap-token.txt').read_text().strip()
        assert c.get('/api/bootstrap').json()['needs_setup']
        assert c.post('/api/setup',json={'token':token,'username':'auditor','password':'long-unique-password'}).status_code==200
        session=c.post('/api/login',json={'username':'auditor','password':'long-unique-password'})
        assert session.status_code==200
        c.headers['X-CSRF-Token']=session.json()['csrf']
        yield c

def make_doc(body,heading='Course Description'):
    doc=Document(); doc.add_heading('CSC-220',0);doc.add_heading(heading,1)
    for x in body:doc.add_paragraph(x)
    stream=io.BytesIO();doc.save(stream);return stream.getvalue()

def test_auth_and_institution(client):
    unauth=TestClient(main.app)
    assert unauth.get('/api/institutions').status_code==401
    assert client.get('/api/me').json()['role']=='admin'
    res=client.post('/api/institutions',json={'name':'Sample Community College','catalog_url':'https://college.example.edu/catalog','allowed_hosts':'policies.example.edu','academic_year':'2026-2027'})
    assert res.status_code==200,res.text
    assert client.get('/api/overview').json()['institutions']==1

def test_document_parsing_and_validation(client,tmp_path):
    p=tmp_path/'sample.docx';p.write_bytes(make_doc(['The official course description exactly as approved.','All submitted work must be your own.'],heading='Course Descrption'))
    parsed=extract(p)
    assert infer_course_code(parsed['text'])=='CSC-220'
    assert parsed['characters']>70
    assert candidate_segments(parsed['blocks'],keys='course description')
    req=[{'id':1,'name':'Academic integrity','category':'policy','mode':'exact','severity':'critical',
          'expected_text':'All submitted work must be your own.','variants_json':'[]','keywords':'integrity,submitted work','source_url':'','active':1}]
    code,found=audit_document(parsed,req,use_ai=False)
    assert code=='CSC-220'
    assert found[0]['status']=='review' # no approved course catalog reference
    assert any(x['status']=='passed' and x['category']=='policy' for x in found)
    req[0]['expected_text']='A different official integrity policy.'
    _,found=audit_document(parsed,req,use_ai=False)
    assert any(x['status'] in ('failed','warning') and x['category']=='policy' for x in found)

def test_requirement_course_audit_and_reports(client):
    ins=client.get('/api/institutions').json()[0]['id']
    c=client.post('/api/courses',json={'institution_id':ins,'code':'CSC-220','title':'Foundations of Computation',
         'description':'The official course description exactly as approved.','credits':'3',
         'academic_year':'2026-2027','source_url':'https://college.example.edu/catalog/CSC220'})
    assert c.status_code==200,c.text
    course=c.json()['id']
    # Mark only the test record verified; live website checks are tested separately.
    execute('UPDATE courses SET last_verified_at=? WHERE id=?',('2026-11-13T14:00:00+00:00',course))
    r=client.post('/api/requirements',json={'institution_id':ins,'name':'Academic integrity',
      'category':'policy','mode':'exact','severity':'critical','expected_text':'All submitted work must be your own.',
      'keywords':'integrity,submitted work'})
    assert r.status_code==200,r.text
    doc=make_doc(['The official course description exactly as approved.','All submitted work must be your own.'])
    upload=client.post('/api/audits/upload',data={'institution_id':ins,'template_id':0,'academic_year':'2026-2027'},
                       files=[('files',('course.docx',doc,'application/vnd.openxmlformats-officedocument.wordprocessingml.document'))])
    assert upload.status_code==200,upload.text
    job=upload.json()['job_id']
    for i in range(100):
        result=client.get(f'/api/jobs/{job}').json()
        if result['job']['status'] in ('complete','complete_with_errors'):break
        time.sleep(.08)
    assert result['job']['status']=='complete',result
    audit=result['audits'][0]
    assert audit['passed']>=2,audit
    report=client.get(f'/api/audits/{audit["id"]}/report.pdf')
    assert report.status_code==200 and report.content.startswith(b'%PDF')
    docx=client.get(f'/api/audits/{audit["id"]}/report.docx')
    assert docx.status_code==200 and docx.content.startswith(b'PK')
    assert client.get(f'/api/jobs/{job}/export.zip').content.startswith(b'PK')
    assert client.get('/api/audits/export.csv').content.startswith(b'\xef\xbb\xbf')
    assert client.get(f'/api/audits/{audit["id"]}/document').status_code==200


def test_template_upload_and_edit(client):
    ins=client.get('/api/institutions').json()[0]['id']
    doc=make_doc(['The official description.'])
    response=client.post('/api/templates/upload',data={'institution_id':ins,'name':'Standard Syllabus','academic_year':'2026-2027'},
     files={'file':('template.docx',doc,'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
    assert response.status_code==200,response.text
    tid=response.json()['id']
    record=next(x for x in client.get('/api/templates',params={'institution_id':ins}).json() if x['id']==tid)
    sections=__import__('json').loads(record['sections_json'])
    assert sections
    sections[0]['required']=True
    r=client.put(f'/api/templates/{tid}',json={'sections_json':sections,'name':'Standard Revised'})
    assert r.status_code==200
    assert next(x for x in client.get('/api/templates').json() if x['id']==tid)['version']==2


def test_sources_are_restricted_and_changes_are_staged(client,monkeypatch):
    institution=client.get('/api/institutions').json()[0]
    for url in ['http://college.example.edu/catalog','https://127.0.0.1/policy','https://malicious.example.org/']:
        with pytest.raises(ValueError):validate_url(url,institution)
    course=client.get('/api/courses',params={'institution_id':institution['id']}).json()[0]
    fake={'url':'https://college.example.edu/catalog/CSC220','text':'CSC-220 NEW description. The description has changed.',
          'links':[],'content_type':'text/html'}
    monkeypatch.setattr('app.sources.fetch_source',lambda url,inst:fake)
    response=client.post('/api/sources/check',json={'institution_id':institution['id'],'target_type':'course','target_id':course['id']})
    assert response.status_code==200 and response.json()['status']=='changed'
    change_id=response.json()['id']
    assert client.post(f'/api/sources/{change_id}/approve',json={'approved_text':'NEW description.'}).status_code==200
    assert one('SELECT description FROM courses WHERE id=?',(course['id'],))['description']=='NEW description.'
    assert all_rows('SELECT * FROM revisions WHERE kind="course"')


def test_csrf_and_invalid_upload(client):
    cookie=client.cookies.get('sa_session')
    x=TestClient(main.app)
    x.cookies.set('sa_session',cookie)
    assert x.post('/api/institutions',json={'name':'Should fail'}).status_code==403
    ins=client.get('/api/institutions').json()[0]['id']
    bad=client.post('/api/audits/upload',data={'institution_id':ins},files=[('files',('bad.exe',b'abc','application/octet-stream'))])
    assert bad.status_code==400
