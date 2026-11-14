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


def test_approved_domain_trailing_slash_is_normalized(client, monkeypatch):
    """The institution form may receive a trailing slash after a hostname."""
    import socket
    from app.sources import _allowed_hosts
    inst = client.get('/api/institutions').json()[0]
    response = client.put(f"/api/institutions/{inst['id']}", json={
        'allowed_hosts': 'policies.example.edu, colss-prod.ec.sunyocc.edu/'
    })
    assert response.status_code == 200, response.text
    updated = client.get('/api/institutions').json()[0]
    assert 'colss-prod.ec.sunyocc.edu/' not in updated['allowed_hosts']
    assert 'colss-prod.ec.sunyocc.edu' in _allowed_hosts(updated)
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))
    ])
    assert validate_url('https://colss-prod.ec.sunyocc.edu/Student/Courses', updated)
    # Full HTTPS links now normalize to their hostname, leaving the
    # preexisting comma-separated database field and validation intact.
    url_input = client.put(f"/api/institutions/{inst['id']}", json={
        'allowed_hosts': 'https://colss-prod.ec.sunyocc.edu/Student/Courses/Search?subjects=CIS, policies.example.edu'
    })
    assert url_input.status_code == 200, url_input.text
    updated = client.get('/api/institutions').json()[0]
    assert updated['allowed_hosts'] == 'colss-prod.ec.sunyocc.edu, policies.example.edu'
    assert validate_url('https://colss-prod.ec.sunyocc.edu/Student/Courses',updated)
    for invalid in ('http://colss-prod.ec.sunyocc.edu/Student/Courses',
                    'https://user:pass@colss-prod.ec.sunyocc.edu/foo',
                    'https://colss-prod.ec.sunyocc.edu:8080/Student/Courses',
                    'colss-prod.ec.sunyocc.edu/Student/Courses'):
        bad = client.put(f"/api/institutions/{inst['id']}",json={'allowed_hosts':invalid})
        assert bad.status_code == 400, (invalid,bad.text)

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


def test_bulk_catalog_scan_preview_and_apply(client,monkeypatch):
    """Full preview/approval flow without any external website dependency."""
    from app import catalog_bulk as cb
    ins=client.get('/api/institutions').json()[0]
    base=ins['catalog_url']
    pages={
        base:{'text':'College catalog\nCourse descriptions','links':[
            {'url':base+'/cis-125','label':'CIS 125 - Introduction to CIS'},
            {'url':base+'/csc-220','label':'CSC 220 - Foundations of Computation'},
            {'url':base+'/mat-101','label':'MAT 101 - College Algebra'}]},
        base+'/cis-125':{'text':'CIS 125 - Introduction to Computer Information Systems\nCredits: 3\nA comprehensive introduction to computer information systems and practical software fundamentals, including information literacy.','links':[]},
        base+'/csc-220':{'text':'CSC 220 - Foundations of Computation\n3 Credit Hours\nA revised official course description discussing formal languages, logic, and computation theory for students.','links':[]},
        base+'/mat-101':{'text':'MAT 101 - College Algebra\nPrerequisite: Basic algebra\nCollege Algebra provides a foundation in equations, inequalities, functions and graphing methods.','links':[]},
    }
    monkeypatch.setattr(cb,'validate_url',lambda url,institution:True)
    monkeypatch.setattr(cb,'fetch_source',lambda url,institution:{'url':url,'text':pages[url]['text'],'links':pages[url]['links']})
    from app.database import execute
    import time
    job_id=execute('INSERT INTO catalog_imports(institution_id,created_by,seed_url,academic_year,max_pages,created_at) VALUES(?,?,?,?,?,?)',
                   (ins['id'],1,base,'2026-2027',10,'2026-11-13T00:00:00+00:00'))
    cb.scan_catalog(job_id,ins)
    report=client.get(f'/api/catalog-imports/{job_id}')
    assert report.status_code==200,report.text
    data=report.json()
    assert data['status']=='ready' and data['courses_found']==3,data
    assert data['counts']['changed']==1,data
    assert data['counts']['new']==2,data
    rows=client.get(f'/api/catalog-imports/{job_id}/items',params={'q':'cis'}).json()
    assert rows['total']==1 and rows['items'][0]['code']=='CIS-125'
    assert len(rows['items'][0]['description'])>50
    result=client.post(f'/api/catalog-imports/{job_id}/apply',json={'update_existing':False})
    assert result.status_code==200,result.text
    assert result.json()['created']==2 and result.json()['updated']==0,result.json()
    new_course=one('SELECT * FROM courses WHERE institution_id=? AND code=? AND academic_year=?',(ins['id'],'CIS-125','2026-2027'))
    assert new_course and new_course['description'] and not new_course['last_verified_at']
    old_course=one('SELECT * FROM courses WHERE institution_id=? AND code=? AND academic_year=?',(ins['id'],'CSC-220','2026-2027'))
    assert 'revised' not in old_course['description'].lower()
    result=client.post(f'/api/catalog-imports/{job_id}/apply',json={'update_existing':True})
    assert result.status_code==200 and result.json()['updated']==1,result.text
    updated=one('SELECT * FROM courses WHERE id=?',(old_course['id'],))
    assert 'revised' in updated['description'].lower() and updated['version']==old_course['version']+1
    assert updated['last_verified_at']==''
    assert client.post('/api/catalog-imports',json={'institution_id':ins['id'],'seed_url':'https://evil.example.net/','academic_year':'2026-2027'}).status_code==400
    assert client.get('/api/catalog-imports',params={'institution_id':ins['id']}).status_code==200


def test_bulk_catalog_empty_access_error(client,monkeypatch):
    from app import catalog_bulk as cb
    from app.database import execute
    inst=client.get('/api/institutions').json()[0]
    monkeypatch.setattr(cb,'validate_url',lambda *args:True)
    def denied(*args):raise ValueError('403 Forbidden')
    monkeypatch.setattr(cb,'fetch_source',denied)
    ident=execute('INSERT INTO catalog_imports(institution_id,created_by,seed_url,academic_year,max_pages,created_at) VALUES(?,?,?,?,?,?)',
      (inst['id'],1,inst['catalog_url'],'2026-2027',5,'2026-11-13T00:00:00+00:00'))
    cb.scan_catalog(ident,inst)
    result=client.get(f'/api/catalog-imports/{ident}').json()
    assert result['status']=='failed' and '403' in result['error']
    assert client.post(f'/api/catalog-imports/{ident}/apply',json={'update_existing':False}).status_code==400


def test_bulk_catalog_start_api_and_access_control(client,monkeypatch):
    from app import catalog_bulk as cb
    from app import sources
    import time
    inst=client.get('/api/institutions').json()[0]
    page={'url':inst['catalog_url'],'text':'BIO 110 - Principles of Biology\n3 Credit Hours\nThis introductory laboratory biology course investigates scientific reasoning, cell structures, heredity, ecology, and organisms.','links':[]}
    monkeypatch.setattr(cb,'validate_url',lambda *args:True)
    monkeypatch.setattr(sources,'validate_url',lambda *args:True)
    monkeypatch.setattr(cb,'fetch_source',lambda *args:page)
    result=client.post('/api/catalog-imports',json={'institution_id':inst['id'],'academic_year':'2027-2028','max_pages':10})
    assert result.status_code==200,result.text
    ident=result.json()['id']
    for _ in range(60):
        check=client.get(f'/api/catalog-imports/{ident}').json()
        if check['status']!='running':break
        time.sleep(.05)
    assert check['status']=='ready',check
    assert check['counts']['new']==1,check
    assert client.get(f'/api/catalog-imports/{ident}/items',params={'offset':-1}).status_code==400
    # No accidental approval without explicit POST action.
    assert one('SELECT * FROM courses WHERE institution_id=? AND code=? AND academic_year=?',(inst['id'],'BIO-110','2027-2028')) is None


def test_acalog_form_prefix_scan_and_course_previews(client,monkeypatch):
    """OCC's catalog lists courses via Acalog filter forms, not only hrefs."""
    from app import catalog_bulk as cb
    from urllib.parse import urlsplit,parse_qs
    inst=client.get('/api/institutions').json()[0].copy()
    base='https://catalog.sunyocc.edu/content.php?catoid=15&navoid=755'
    inst['catalog_url']=base
    inst['allowed_hosts']='catalog.sunyocc.edu'
    seed_html='''<html><body><h1>Course Descriptions</h1>
      <form action="content.php" method="get">
      <select name="filter[27]"><option value="-1">All</option>
      <option value="CIS">Computer Information Systems</option>
      <option value="CSC">Computer Science</option></select></form></body></html>'''
    detail={
      '1001':('CIS 125 - Introduction to Information Systems',
       'This official catalog description covers information systems, computers, digital literacy, and workplace productivity applications.'),
      '2002':('CSC 220 - Foundations of Computation',
       'The official course introduces formal logic, sets, computational models, languages, and automata for computing students.'),
    }
    def fake_fetch(url,institution):
        params=parse_qs(urlsplit(url).query)
        if url==base:
            return {'url':url,'text':'Course Descriptions', 'links':[],'html':seed_html}
        if 'coid' in params:
            heading,description=detail[params['coid'][0]]
            return {'url':url,'text':heading+'\n3 Credits\n'+description, 'links':[], 'html':''}
        if 'filter[27]' in params:
            prefix=params['filter[27]'][0]
            coid={'CIS':'1001','CSC':'2002'}[prefix]
            heading,_=detail[coid]
            return {'url':url,'text':'Courses under '+prefix,
                    'links':[{'label':heading,'url':f'https://catalog.sunyocc.edu/preview_course_nopop.php?catoid=15&coid={coid}'}],
                    'html':''}
        raise AssertionError('Unexpected outside-catalog URL: '+url)
    monkeypatch.setattr(cb,'validate_url',lambda *a: True)
    monkeypatch.setattr(cb,'fetch_source',fake_fetch)
    job=execute('''INSERT INTO catalog_imports(institution_id,created_by,seed_url,academic_year,max_pages,created_at)
                VALUES(?,?,?,?,?,?)''',(inst['id'],1,base,'2026-2027',20,'2026-11-13T00:00:00+00:00'))
    cb.scan_catalog(job,inst)
    result=client.get(f'/api/catalog-imports/{job}').json()
    assert result['status']=='ready' and result['courses_found']==2,result
    assert result['pages_scanned']==5,result
    rows=client.get(f'/api/catalog-imports/{job}/items').json()['items']
    assert all(len(row['description'])>50 for row in rows),rows
    assert {row['code'] for row in rows}=={'CIS-125','CSC-220'}
    assert all('preview_course_nopop.php' in row['source_url'] for row in rows)
    # No import is performed until an administrator explicitly approves it.
    assert all(row['status'] in ('new','changed','unchanged') for row in rows)


def test_acalog_empty_200_page_fails_not_ready(client,monkeypatch):
    from app import catalog_bulk as cb
    inst=client.get('/api/institutions').json()[0].copy()
    base='https://catalog.sunyocc.edu/content.php?catoid=15&navoid=755'
    inst['catalog_url']=base
    monkeypatch.setattr(cb,'validate_url',lambda *a: True)
    monkeypatch.setattr(cb,'fetch_source',lambda *a:{'url':base,'text':'Course Catalog home page', 'links':[], 'html':'<html><body>Course Catalog home page</body></html>'})
    job=execute('''INSERT INTO catalog_imports(institution_id,created_by,seed_url,academic_year,max_pages,created_at)
                VALUES(?,?,?,?,?,?)''',(inst['id'],1,base,'2026-2027',20,'2026-11-13T00:00:00+00:00'))
    cb.scan_catalog(job,inst)
    result=client.get(f'/api/catalog-imports/{job}').json()
    assert result['status']=='failed' and result['courses_found']==0,result
    assert 'No course records were found' in result['error']
    assert client.post(f'/api/catalog-imports/{job}/apply',json={'update_existing':True}).status_code==400


def test_acalog_does_not_follow_unrelated_catalog_years():
    from app.catalog_bulk import _relevant_link
    seed='https://catalog.sunyocc.edu/content.php?catoid=15&navoid=755'
    def check(url):return _relevant_link({'url':url,'label':'CIS 125'},seed)
    assert check('https://catalog.sunyocc.edu/preview_course_nopop.php?catoid=15&coid=1001')
    assert not check('https://catalog.sunyocc.edu/preview_course_nopop.php?catoid=14&coid=1001')
    assert not check('https://catalog.sunyocc.edu/content.php?catoid=15&navoid=777')


def test_acalog_fallback_pagination_only_scans_selected_catalog():
    from app.catalog_bulk import _acalog_pagination_urls
    from urllib.parse import parse_qs,urlsplit
    seed='https://catalog.sunyocc.edu/content.php?catoid=15&navoid=755'
    first=seed+'&filter%5B27%5D=CIS&filter%5Bcpage%5D=1'
    page={'html':'<html><body><select name="filter[cpage]"><option value="1">1</option><option value="2">2</option><option value="3">3</option></select></body></html>','text':'Courses'}
    pages=_acalog_pagination_urls(page,first,seed)
    assert len(pages)==2
    assert [parse_qs(urlsplit(u).query)['filter[cpage]'][0] for u in pages]==['2','3']
    assert all('catoid=15' in u and 'navoid=755' in u for u in pages)
    assert _acalog_pagination_urls(page,pages[0],seed)==[]
    assert _acalog_pagination_urls(page,first,seed.replace('catoid=15','catoid=14'))==[]


def test_browser_catalog_capture_json_is_staged_and_unverified(client):
    import json
    inst=client.get('/api/institutions').json()[0]
    seed='https://college.example.edu/content.php?catoid=15&navoid=755'
    capture={
       'format':'syllabus-auditor-browser-capture-v1','source_url':seed,
       'pages_checked':14,'complete':True,'errors':[],
       'courses':[
        {'code':'CIS 125','title':'Fundamentals of Computer Information Systems',
         'description':'An introduction to computer systems, software, hardware and practical information systems applications.',
         'credits':'3','source_url':'https://college.example.edu/preview_course_nopop.php?catoid=15&coid=100'},
        {'code':'CIS-125','title':'Fundamentals of Computer Information Systems',
         'description':'', 'source_url':seed},
        {'code':'CSC-112','title':'Fundamentals of Computing II',
         'description':'Java and programming with data structures, object-oriented design, recursion and computational methods.',
         'credits':'4','source_url':'https://college.example.edu/preview_course_nopop.php?catoid=15&coid=101'},
        {'code':'HST-200','title':'Wrong origin','description':'This course should not import.',
         'source_url':'https://evil.example.edu/preview_course_nopop.php?catoid=15&coid=1'}]}
    result=client.post('/api/catalog-imports/capture',data={
        'institution_id':inst['id'],'academic_year':'2026-2027','seed_url':seed},
        files={'file':('OCC_Catalog_15_Browser_Capture.json',json.dumps(capture).encode(),'application/json')})
    assert result.status_code==200,result.text
    job=result.json()
    assert job['courses_found']==2 and job['complete'] is False
    report=client.get(f"/api/catalog-imports/{job['id']}").json()
    assert (report['counts'].get('new',0)+report['counts'].get('changed',0)+report['counts'].get('unchanged',0))>=2
    items=client.get(f"/api/catalog-imports/{job['id']}/items").json()['items']
    course=next(x for x in items if x['code']=='CIS-125')
    assert 'computer systems' in course['description']
    assert all('evil.example.edu' not in x['source_url'] for x in items)
    # Importing occurs only after explicit approval; imported references are unverified.
    applied=client.post(f"/api/catalog-imports/{job['id']}/apply",json={'update_existing':False})
    assert applied.status_code==200
    stored=one('SELECT * FROM courses WHERE institution_id=? AND code=? AND academic_year=?',
             (inst['id'],'CIS-125','2026-2027'))
    assert stored and not stored['last_verified_at']


def test_browser_catalog_capture_rejects_cross_catalog_and_empty(client):
    import json
    inst=client.get('/api/institutions').json()[0]
    seed='https://college.example.edu/content.php?catoid=15&navoid=755'
    def upload(capture,name='capture.json'):
        return client.post('/api/catalog-imports/capture',data={
            'institution_id':inst['id'],'academic_year':'2026-2027','seed_url':seed},
            files={'file':(name,json.dumps(capture).encode(),'application/json')})
    assert upload({'source_url':'https://elsewhere.example.org/content.php?catoid=15&navoid=755','courses':[]}).status_code==400
    assert upload({'source_url':'https://college.example.edu/content.php?catoid=16&navoid=755','courses':[]}).status_code==400
    assert upload({'source_url':seed,'courses':[]}).status_code==400
    assert upload({'source_url':seed,'courses':[{'code':'CIS 125','title':'Some title','description':''}]}).status_code==400


def test_saved_html_capture_can_extract_courseblock(client):
    inst=client.get('/api/institutions').json()[0]
    seed='https://college.example.edu/content.php?catoid=15&navoid=755'
    saved_html=b'''<html><body><div class="courseblock">
      <p class="courseblocktitle">CIS 130 - Web Development</p>
      <p class="courseblockdesc">An introductory course in HTML and CSS, browser development and building responsive websites.</p>
      <p>3 credits</p>
      </div></body></html>'''
    res=client.post('/api/catalog-imports/capture',data={
      'institution_id':inst['id'],'academic_year':'2026-2027','seed_url':seed},
      files={'file':('catalog.html',saved_html,'text/html')})
    assert res.status_code==200,res.text
    assert res.json()['complete'] is False
    items=client.get(f"/api/catalog-imports/{res.json()['id']}/items").json()['items']
    assert any(x['code']=='CIS-130' and 'responsive websites' in x['description'] for x in items)


def test_filtered_acalog_url_accepts_cur_cat_oid_and_keeps_subject_scope():
    from app.catalog_bulk import _catalog_id, _subject_filter, _relevant_link, _acalog_urls, _acalog_pagination_urls
    from urllib.parse import parse_qs, urlsplit
    base=('https://catalog.sunyocc.edu/content.php?filter%5B27%5D=CIS&filter%5B32%5D=1'
          '&filter%5Bcpage%5D=1&cur_cat_oid=15&navoid=755&search_database=Filter')
    assert _catalog_id(base) == '15'
    assert _subject_filter(base) == 'CIS'
    assert _catalog_id('https://catalog.sunyocc.edu/preview_course_nopop.php?catoid=15&coid=100') == '15'
    assert _relevant_link({'url':'https://catalog.sunyocc.edu/preview_course_nopop.php?catoid=15&coid=100','label':'CIS 125'},base)
    assert not _relevant_link({'url':'https://catalog.sunyocc.edu/preview_course_nopop.php?catoid=14&coid=100','label':'CIS 125'},base)
    assert not _relevant_link({'url':base.replace('CIS','CSC'),'label':'CSC 112'},base)
    html='<html><body><select name="filter[27]"><option value="CIS">CIS</option><option value="CSC">CSC</option></select></body></html>'
    links=_acalog_urls({'html':html},base)
    assert len(links)==1
    params=parse_qs(urlsplit(links[0]).query)
    assert params['filter[27]']==['CIS']
    assert params['cur_cat_oid']==['15']
    assert params['filter[32]']==['1']
    pages=_acalog_pagination_urls({'html':'<select name="filter[cpage]"><option value="1">1</option><option value="2">2</option></select>','text':''},links[0],base)
    assert len(pages)==1
    assert parse_qs(urlsplit(pages[0]).query)['filter[cpage]']==['2']


def test_filtered_browser_capture_accepts_detail_catoid_and_excludes_other_subjects(client):
    import json
    inst=client.get('/api/institutions').json()[0]
    filtered=('https://college.example.edu/content.php?filter%5B27%5D=CIS&filter%5B32%5D=1'
              '&filter%5Bcpage%5D=1&cur_cat_oid=15&navoid=755&search_database=Filter')
    payload={'format':'syllabus-auditor-browser-capture-v1','source_url':filtered,'complete':True,
             'pages_checked':2,'courses':[
                {'code':'CIS-125','title':'Intro to Information Systems',
                 'description':'An introductory course about computing, hardware, software, and practical systems.',
                 'source_url':'https://college.example.edu/preview_course_nopop.php?catoid=15&coid=102'},
                {'code':'CSC-112','title':'Data Structures',
                 'description':'A course on implementation and study of common data structures.',
                 'source_url':'https://college.example.edu/preview_course_nopop.php?catoid=15&coid=103'}]}
    res=client.post('/api/catalog-imports/capture',data={
       'institution_id':inst['id'],'academic_year':'2026-2027','seed_url':filtered},
       files={'file':('CIS_capture.json',json.dumps(payload).encode(),'application/json')})
    assert res.status_code==200,res.text
    result=res.json()
    assert result['courses_found']==1
    assert not result['complete']
    rows=client.get(f"/api/catalog-imports/{result['id']}/items").json()['items']
    assert [r['code'] for r in rows]==['CIS-125']
    assert 'computing' in rows[0]['description']
    different=payload.copy();different['source_url']=filtered.replace('cur_cat_oid=15','cur_cat_oid=14')
    fail=client.post('/api/catalog-imports/capture',data={
       'institution_id':inst['id'],'academic_year':'2026-2027','seed_url':filtered},
       files={'file':('wrong_catalog.json',json.dumps(different).encode(),'application/json')})
    assert fail.status_code==400


def test_filtered_html_capture_only_imports_requested_subject(client):
    inst=client.get('/api/institutions').json()[0]
    filtered='https://college.example.edu/content.php?cur_cat_oid=15&navoid=755&filter%5B27%5D=CIS'
    html=b'''<html><body>
      <div class="courseblock"><p class="courseblocktitle">CIS 130 - Web Design</p>
      <p class="courseblockdesc">This course teaches accessible HTML, CSS, and responsive web design.</p></div>
      <div class="courseblock"><p class="courseblocktitle">CSC 112 - Programming</p>
      <p class="courseblockdesc">This course teaches Java programming with structured exercises.</p></div>
      </body></html>'''
    res=client.post('/api/catalog-imports/capture',data={
        'institution_id':inst['id'],'academic_year':'2026-2027','seed_url':filtered},
        files={'file':('CIS.html',html,'text/html')})
    assert res.status_code==200,res.text
    rows=client.get(f"/api/catalog-imports/{res.json()['id']}/items").json()['items']
    assert len(rows)==1 and rows[0]['code']=='CIS-130'


def test_saved_html_acalog_expanded_course_headers(client):
    '''OCC-style expanded headers need not use a dash between code and title.'''
    inst=client.get('/api/institutions').json()[0]
    source='https://college.example.edu/content.php?cur_cat_oid=15&navoid=755&filter%5B27%5D=CIS'
    html=b'''<html><body>
      <div class="acalog-course" id="course_1">
        <div class="acalog-course-header"><strong>CIS 125 Introduction to Computer Information Systems</strong></div>
        <div class="acalog-course-description">3 Credit Hours. This course introduces computing systems, software, hardware, digital applications, and their use in business.</div>
      </div>
      <div class="acalog-course" id="course_2">
        <div class="acalog-course-header"><strong>CIS 130 - Web Development</strong></div>
        <div class="acalog-course-description">Students learn HTML, CSS, accessible web design, responsive interfaces and testing practices.</div>
      </div>
      <div class="acalog-course" id="course_3">
        <div class="acalog-course-header"><strong>CSC 112 - Data Structures</strong></div>
        <div class="acalog-course-description">This other subject is not part of the chosen CIS import.</div>
      </div>
    </body></html>'''
    response=client.post('/api/catalog-imports/capture',data={
        'institution_id':inst['id'],'academic_year':'2026-2027','seed_url':source},
        files={'file':('expanded.html',html,'text/html')})
    assert response.status_code==200,response.text
    rows=client.get(f"/api/catalog-imports/{response.json()['id']}/items").json()['items']
    assert {r['code'] for r in rows} == {'CIS-125','CIS-130'}
    assert 'computing systems' in next(r for r in rows if r['code']=='CIS-125')['description']


def test_myocc_self_service_capture_with_subject_filter(client):
    import json
    from app.catalog_bulk import _subject_filter, _self_service, _capture_source_compatible
    base='https://colss-prod.ec.sunyocc.edu/Student/Courses/Search?subjects=CIS'
    assert _self_service(base)
    assert _subject_filter(base)=='CIS'
    assert _capture_source_compatible(base,base)
    assert not _capture_source_compatible(base,'https://colss-prod.ec.sunyocc.edu/Student/Courses/Search?subjects=CSC')
    assert not _capture_source_compatible(base,'https://catalog.sunyocc.edu/content.php?catoid=15&navoid=755')
    inst=client.get('/api/institutions').json()[0]['id']
    current=client.get('/api/institutions').json()[0]
    hosts=current['allowed_hosts'] or ''
    res=client.put(f'/api/institutions/{inst}',json={'allowed_hosts':hosts+',colss-prod.ec.sunyocc.edu'})
    assert res.status_code==200,res.text
    payload={'format':'syllabus-auditor-browser-capture-v1','source_url':base,'complete':False,
      'errors':['Only rendered results included'],'pages_checked':1,'courses':[
       {'code':'CIS-100','title':'Information and Computer Literacy','description':'An overview of computing and information technologies with research and communication skills.','credits':'3','source_url':base},
       {'code':'CSC-112','title':'Data Structures','description':'Out of scope for CIS.','credits':'4','source_url':base}]}
    resp=client.post('/api/catalog-imports/capture',data={'institution_id':inst,'academic_year':'2026-2027','seed_url':base},files={'file':('capture.json',json.dumps(payload).encode(),'application/json')})
    assert resp.status_code==200,resp.text
    report=resp.json()
    assert report['courses_found']==1
    assert report['complete'] is False
    out=client.get(f'/api/catalog-imports/{report["id"]}/items').json()
    assert out['total']==1
    assert out['items'][0]['code']=='CIS-100'


def test_myocc_bulk_scan_stages_results_in_existing_review_workflow(client,monkeypatch):
    """Regression: MyOCC must use dynamic-browser source and stage data, not auto-verify."""
    from app import sources, catalog_bulk, myocc_bulk
    inst=client.get('/api/institutions').json()[0]
    if 'colss-prod.ec.sunyocc.edu' not in inst['allowed_hosts']:
        assert client.put(f'/api/institutions/{inst["id"]}',json={
            'allowed_hosts':(inst['allowed_hosts'] or '')+',colss-prod.ec.sunyocc.edu'}).status_code==200
    captured={}
    def pretend_collect(url, institution, subjects, max_pages, progress):
        captured.update({'url':url,'subjects':subjects,'pages':max_pages})
        progress(2,2)
        return ([
            {'code':'CIS-101','title':'Computing Fundamentals',
             'description':'Fundamental computing concepts, information technology, and everyday applications.',
             'credits':'3','prerequisites':'',
             'source_url':'https://colss-prod.ec.sunyocc.edu/Student/Courses/Search?subjects=CIS',
             'evidence':'CIS-101 Computing Fundamentals'},
            {'code':'CSC-212','title':'Software Analysis',
             'description':'Methods and techniques for analyzing and designing software solutions.',
             'credits':'3','prerequisites':'',
             'source_url':'https://colss-prod.ec.sunyocc.edu/Student/Courses/Search?subjects=CSC',
             'evidence':'CSC-212 Software Analysis'}
        ],2,True,['MyOCC result coverage could not be verified'])
    monkeypatch.setattr(myocc_bulk,'collect_myocc',pretend_collect)
    monkeypatch.setattr(sources,'validate_url',lambda *args: True)
    monkeypatch.setattr(catalog_bulk,'validate_url',lambda *args: True)
    start=client.post('/api/catalog-imports',json={
        'institution_id':inst['id'],'seed_url':'https://colss-prod.ec.sunyocc.edu/Student/Courses',
        'academic_year':'2026-2027','subject_codes':'CIS,CSC','max_pages':250})
    assert start.status_code==200,start.text
    ident=start.json()['id'];job=None
    for _ in range(80):
        job=client.get(f'/api/catalog-imports/{ident}').json()
        if job['status'] in ('ready','failed'):break
        time.sleep(.05)
    assert job['status']=='ready',job
    assert job['courses_found']==2 and job['pages_scanned']==2
    assert job['truncated']==1
    assert captured['subjects']==['CIS','CSC']
    rows=client.get(f'/api/catalog-imports/{ident}/items').json()['items']
    assert {r['code'] for r in rows}=={'CIS-101','CSC-212'}
    assert job['errors']
    assert not any(c['code']=='CIS-101' for c in client.get('/api/courses?institution_id='+str(inst['id'])).json())
    applied=client.post(f'/api/catalog-imports/{ident}/apply',json={'update_existing':False})
    assert applied.status_code==200,applied.text
    assert applied.json()['created']==2
    saved=next(c for c in client.get('/api/courses?institution_id='+str(inst['id'])).json() if c['code']=='CIS-101')
    assert saved['last_verified_at']==''
    assert saved['academic_year']=='2026-2027'


def test_myocc_bulk_rejects_incorrect_subject_codes(client,monkeypatch):
    from app import sources
    monkeypatch.setattr(sources,'validate_url',lambda *args: True)
    inst=client.get('/api/institutions').json()[0]
    start=client.post('/api/catalog-imports',json={
        'institution_id':inst['id'],
        'seed_url':'https://colss-prod.ec.sunyocc.edu/Student/Courses',
        'academic_year':'2026-2027',
        'subject_codes':'CIS,../../../admin',
        'max_pages':20})
    assert start.status_code==400


def test_myocc_bulk_subject_path_construction(monkeypatch):
    from app import myocc_bulk
    urls=[]
    class DummyPage:
        def goto(self,url,**kw):urls.append(url)
        def wait_for_timeout(self,ms):pass
        def evaluate(self,script):return ['CIS','CSC']
    page=DummyPage()
    result=myocc_bulk._subjects_for_scan(page,'https://colss-prod.ec.sunyocc.edu/Student/Courses',[])
    assert result==['CIS','CSC']
    assert urls==['https://colss-prod.ec.sunyocc.edu/Student/Courses']
    assert myocc_bulk._subjects_for_scan(page,
        'https://colss-prod.ec.sunyocc.edu/Student/Courses/Search?subjects=MATH',[]) == ['MATH']


def test_course_title_uses_actual_catalog_value_and_not_unrelated_heading():
    from app.validation import audit_document
    course = {'code':'CIS-125', 'title':'Fundamentals of CIS',
        'description':'The exact course description from the catalog.',
        'academic_year':'2026-2027','last_verified_at':'2026-11-13',
        'source_url':'https://colss-prod.ec.sunyocc.edu/Student/Courses/Search?subjects=CIS'}
    blocks = [
        {'text':'CIS-125 Fundamentals of CIS','location':'Paragraph 1','kind':'heading'},
        {'text':'Course description','location':'Paragraph 2','kind':'heading'},
        {'text':'The exact course description from the catalog.','location':'Paragraph 3','kind':'paragraph'},
    ]
    blocks += [{'text':f'Unrelated section {i}','location':f'Paragraph {i}','kind':'paragraph'} for i in range(4,34)]
    blocks.append({'text':'Course Materials and Support','location':'Paragraph 34','kind':'heading'})
    blocks.append({'text':'Course materials will be provided through CIS 125.','location':'Paragraph 35','kind':'paragraph'})
    extracted={'text':'\n'.join(b['text'] for b in blocks),'blocks':blocks, 'ocr_pages':[]}
    code,findings = audit_document(extracted,[],course,use_ai=False)
    title=next(f for f in findings if f['code']=='catalog_title')
    assert title['status']=='passed',title
    assert title['expected']=='Fundamentals of CIS'
    assert title['location']=='Paragraph 1'
    assert title['observed']=='CIS-125 Fundamentals of CIS'
    assert 'Course Materials and Support' not in title['observed']
    assert title['source_url']==course['source_url']


def test_course_title_not_located_never_matches_unrelated_course_heading():
    from app.validation import audit_document
    course={'code':'CIS-125','title':'Fundamentals of CIS',
            'source_url':'https://catalog.sunyocc.edu/some-course', 'last_verified_at':'2026-11-13'}
    blocks=[{'text':'CIS-125','location':'Paragraph 1','kind':'heading'},
            {'text':'Course Materials and Support','location':'Paragraph 34','kind':'heading'},
            {'text':'Course materials will be provided through CIS 125-301W D2L Home Page.',
             'location':'Paragraph 35','kind':'paragraph'}]
    extracted={'text':'\n'.join(x['text'] for x in blocks),'blocks':blocks,'ocr_pages':[]}
    _,findings=audit_document(extracted,[],course,use_ai=False)
    title=next(x for x in findings if x['code']=='catalog_title')
    assert title['status']=='review',title
    assert title['observed']=='' and title['location']==''
    assert 'No unrelated section was substituted' in title['explanation']


def test_course_title_label_with_value_on_next_paragraph_and_unverified_source():
    from app.validation import audit_document
    course={'code':'CIS-125','title':'Fundamentals of CIS',
            'source_url':'https://catalog.sunyocc.edu/some-course', 'last_verified_at':''}
    blocks=[{'text':'Course Title:','location':'Paragraph 1','kind':'heading'},
            {'text':'Fundamentals of CIS','location':'Paragraph 2','kind':'paragraph'},
            {'text':'Course Materials and Support','location':'Paragraph 34','kind':'heading'}]
    extracted={'text':'\n'.join(x['text'] for x in blocks),'blocks':blocks,'ocr_pages':[]}
    _,findings=audit_document(extracted,[],course,use_ai=False)
    title=next(x for x in findings if x['code']=='catalog_title')
    assert title['status']=='review',title
    assert title['location']=='Paragraph 2'
    assert 'has not been independently verified' in title['explanation']


def test_untrusted_catalog_title_is_not_treated_as_verified():
    from app.validation import audit_document
    course={'code':'CIS-125','title':'Fundamentals of CIS','source_url':'','last_verified_at':''}
    blocks=[{'text':'Course Name: Fundamentals of CIS','location':'Paragraph 1','kind':'paragraph'}]
    extracted={'text':blocks[0]['text'],'blocks':blocks,'ocr_pages':[]}
    _,findings=audit_document(extracted,[],course,use_ai=False)
    title=next(x for x in findings if x['code']=='catalog_title')
    assert title['status']=='review'
    assert title['observed']=='Course Name: Fundamentals of CIS'


def test_explicit_wrong_title_is_reported_without_matching_other_sections():
    from app.validation import audit_document
    course={'code':'CIS-125','title':'Fundamentals of CIS',
            'last_verified_at':'2026-11-13','source_url':'https://catalog.sunyocc.edu/course'}
    blocks=[{'text':'Course Title: Fundamentals of Biology','location':'Paragraph 1','kind':'paragraph'},
            {'text':'Course Materials and Support','location':'Paragraph 34','kind':'heading'}]
    extracted={'text':'\n'.join(x['text'] for x in blocks),'blocks':blocks,'ocr_pages':[]}
    _,findings=audit_document(extracted,[],course,use_ai=False)
    title=next(x for x in findings if x['code']=='catalog_title')
    assert title['status']=='failed'
    assert title['location']=='Paragraph 1'


def test_generic_course_title_source_is_not_an_approved_value():
    from app.validation import audit_document
    course={'code':'CIS-125','title':'Course title','last_verified_at':'2026-11-13'}
    blocks=[{'text':'Course Title','location':'Paragraph 1','kind':'heading'}]
    extracted={'text':blocks[0]['text'],'blocks':blocks,'ocr_pages':[]}
    _,findings=audit_document(extracted,[],course,use_ai=False)
    title=next(x for x in findings if x['code']=='catalog_title')
    assert title['status']=='review' and title['observed']==''


def _wait_for_job(client, job_id):
    for _ in range(100):
        result=client.get(f'/api/jobs/{job_id}').json()
        if result['job']['status'] in ('complete','complete_with_errors','interrupted'):
            return result
        time.sleep(.04)
    pytest.fail(f'Job {job_id} did not complete')


def test_rerun_existing_report_preserves_previous_results(client):
    """Rerunning uses the stored original but current requirements, without new uploads."""
    institution=client.get('/api/institutions').json()[0]['id']
    document=make_doc(['The official course description exactly as approved.',
                       'All submitted work must be your own.'])
    upload=client.post('/api/audits/upload',data={
        'institution_id':institution,'academic_year':'2026-2027','template_id':0
    },files=[('files',('rerun-test.docx',document,'application/vnd.openxmlformats-officedocument.wordprocessingml.document'))])
    assert upload.status_code==200,upload.text
    original_job=_wait_for_job(client,upload.json()['job_id'])
    original_id=original_job['audits'][0]['id']
    original=client.get(f'/api/audits/{original_id}').json()
    path=Path(original['audit']['storage_path'])
    assert path.exists()
    old_findings=original['findings']
    assert original['audit']['status']=='complete'

    requirement=one('SELECT * FROM requirements WHERE institution_id=? AND name=?',
                    (institution,'Academic integrity'))
    assert requirement
    response=client.put(f'/api/requirements/{requirement["id"]}',json={
        'expected_text':'Assignments must include a documented attribution statement.'})
    assert response.status_code==200,response.text

    queued=client.post(f'/api/audits/{original_id}/rerun')
    assert queued.status_code==200,queued.text
    assert queued.json()['rerun_of_id']==original_id
    new_id=queued.json()['audit_id']
    assert new_id!=original_id
    fresh=_wait_for_job(client,queued.json()['job_id'])
    assert fresh['audits'][0]['id']==new_id
    second=client.get(f'/api/audits/{new_id}').json()
    assert second['audit']['rerun_of_id']==original_id
    assert second['audit']['storage_path']!=str(path)
    assert Path(second['audit']['storage_path']).read_bytes()==path.read_bytes()
    assert second['audit']['status']=='complete'
    assert any('Assignments must include a documented attribution statement.' in f['expected']
               for f in second['findings'])
    assert client.get(f'/api/audits/{original_id}').json()['findings']==old_findings
    assert client.get(f'/api/audits/{new_id}/report.pdf').content.startswith(b'%PDF')
    compare=client.get(f'/api/audits/{new_id}/compare')
    assert compare.status_code==200
    assert compare.json()['previous_audit_id']==original_id

    # Deleting the earlier audit keeps the rerun and its separate saved copy intact.
    deletion=client.delete(f'/api/audits/{original_id}')
    assert deletion.status_code==200,deletion.text
    assert deletion.json()['stored_file_removed'] is True
    assert not path.exists()
    assert client.get(f'/api/audits/{original_id}').status_code==404
    assert client.get(f'/api/jobs/{upload.json()["job_id"]}').status_code==404
    assert client.get(f'/api/audits/{new_id}').status_code==200
    assert Path(second['audit']['storage_path']).is_file()
    assert one('SELECT rerun_of_id FROM audits WHERE id=?',(new_id,))['rerun_of_id'] is None
    assert client.delete(f'/api/audits/{new_id}').status_code==200
    assert client.get(f'/api/audits/{new_id}/report.pdf').status_code==404
    assert not Path(second['audit']['storage_path']).exists()


def test_delete_one_report_preserves_other_batch_records(client):
    inst=client.get('/api/institutions').json()[0]['id']
    upload=client.post('/api/audits/upload',
        data={'institution_id':inst,'academic_year':'2026-2027','template_id':0},
        files=[('files',('batch-a.docx',make_doc(['Batch A content']),'application/vnd.openxmlformats-officedocument.wordprocessingml.document')),
               ('files',('batch-b.docx',make_doc(['Batch B content']),'application/vnd.openxmlformats-officedocument.wordprocessingml.document'))])
    assert upload.status_code==200,upload.text
    job_id=upload.json()['job_id'];done=_wait_for_job(client,job_id)
    a,b=done['audits'];original_path=Path(one('SELECT storage_path FROM audits WHERE id=?',(a['id'],))['storage_path'])
    assert original_path.exists()
    res=client.delete(f'/api/audits/{a["id"]}')
    assert res.status_code==200,res.text
    assert one('SELECT COUNT(*) AS n FROM findings WHERE audit_id=?',(a['id'],))['n']==0
    assert not original_path.exists()
    remain=client.get(f'/api/jobs/{job_id}').json()
    assert remain['job']['total']==1 and remain['job']['finished']==1
    assert len(remain['audits'])==1 and remain['audits'][0]['id']==b['id']
    assert client.get(f'/api/jobs/{job_id}/export.zip').content.startswith(b'PK')
    assert client.delete(f'/api/audits/{b["id"]}').status_code==200
    assert client.get(f'/api/jobs/{job_id}').status_code==404


def test_rerun_and_delete_access_and_missing_document(client):
    inst=client.get('/api/institutions').json()[0]['id']
    upload=client.post('/api/audits/upload',
        data={'institution_id':inst,'academic_year':'2026-2027','template_id':0},
        files=[('files',('private.docx',make_doc(['This is private test content.']),'application/vnd.openxmlformats-officedocument.wordprocessingml.document'))])
    assert upload.status_code==200
    audit=_wait_for_job(client,upload.json()['job_id'])['audits'][0]
    uid=audit['id']
    assert client.delete(f'/api/audits/{uid+999999}').status_code==404
    assert client.post(f'/api/audits/{uid+999999}/rerun').status_code==404
    # The same CSRF enforcement applies to the new mutation endpoints.
    unauth=TestClient(main.app)
    unauth.cookies.set('sa_session',client.cookies.get('sa_session'))
    assert unauth.delete(f'/api/audits/{uid}').status_code==403
    assert unauth.post(f'/api/audits/{uid}/rerun').status_code==403
    user=client.post('/api/users',json={'username':'other_reviewer','password':'very-secure-test-password','role':'reviewer'})
    assert user.status_code==200
    with TestClient(main.app) as reviewer:
        auth=reviewer.post('/api/login',json={'username':'other_reviewer','password':'very-secure-test-password'})
        assert auth.status_code==200
        reviewer.headers['X-CSRF-Token']=auth.json()['csrf']
        assert reviewer.delete(f'/api/audits/{uid}').status_code==403
        assert reviewer.post(f'/api/audits/{uid}/rerun').status_code==403
    path=Path(one('SELECT storage_path FROM audits WHERE id=?',(uid,))['storage_path'])
    path.unlink()
    assert client.post(f'/api/audits/{uid}/rerun').status_code==409
    # Metadata can still be removed if a local file was lost.
    assert client.delete(f'/api/audits/{uid}').status_code==200


def test_existing_database_migrates_without_losing_audits(tmp_path,monkeypatch):
    """An old installation has no rerun_of_id column; startup must add it in place."""
    import sqlite3
    from app import database as database_module
    old_schema=database_module.SCHEMA.replace(' rerun_of_id INTEGER REFERENCES audits(id) ON DELETE SET NULL,\n','')
    filepath=tmp_path/'legacy.sqlite3'
    with sqlite3.connect(filepath) as db:
        db.executescript(old_schema)
        db.execute('INSERT INTO users(id,username,password_hash,role,created_at) VALUES(1,?,?,?,?)',
                   ('legacy','test','admin','2026-01-01'))
        db.execute('INSERT INTO institutions(id,name,created_at) VALUES(1,?,?)',('Legacy college','2026-01-01'))
        db.execute("""INSERT INTO audits(id,institution_id,filename,storage_path,filetype,created_at,created_by,status)
                   VALUES(1,1,'old.docx','saved.docx','.docx','2026-01-01',1,'complete')""")
        db.commit()
    monkeypatch.setattr(database_module,'DB_PATH',filepath)
    database_module.initialize()
    with sqlite3.connect(filepath) as db:
        columns=[row[1] for row in db.execute('PRAGMA table_info(audits)')]
        assert 'rerun_of_id' in columns
        assert db.execute('SELECT filename FROM audits WHERE id=1').fetchone()[0]=='old.docx'


def test_running_batch_cannot_be_deleted(client):
    from app.config import UPLOAD_DIR
    inst=client.get('/api/institutions').json()[0]['id']
    ts=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()
    j=execute('''INSERT INTO audit_jobs(institution_id,academic_year,created_by,created_at,status,total)
                 VALUES(?,?,?,?,?,1)''',(inst,'2026-2027',1,ts,'running'))
    path=UPLOAD_DIR/(secrets.token_hex(12)+'.docx');path.write_bytes(make_doc(['Running batch']))
    a=execute('''INSERT INTO audits(job_id,institution_id,filename,storage_path,filetype,created_at,created_by,status)
                 VALUES(?,?,?,?,?,?,?,?)''',(j,inst,'running.docx',str(path),'.docx',ts,1,'running'))
    try:
        assert client.delete(f'/api/audits/{a}').status_code==409
        assert client.post(f'/api/audits/{a}/rerun').status_code==409
        assert path.exists()
    finally:
        execute('UPDATE audits SET status="error" WHERE id=?',(a,))
        execute('UPDATE audit_jobs SET status="complete_with_errors" WHERE id=?',(j,))
        assert client.delete(f'/api/audits/{a}').status_code==200


def test_reference_record_delete_preserves_audit_findings_and_is_admin_only(client):
    """Removing a policy or catalog source never deletes historical audit evidence."""
    inst=client.get('/api/institutions').json()[0]['id']
    c=client.post('/api/courses',json={'institution_id':inst,'code':'DEL-101','title':'Disposable Course',
                        'description':'This course will be deleted.','academic_year':'2026-2027'})
    assert c.status_code==200,c.text
    cid=c.json()['id']
    req=client.post('/api/requirements',json={'institution_id':inst,'name':'Delete test requirement',
            'mode':'exact','expected_text':'This wording must be included.'})
    assert req.status_code==200,req.text
    rid=req.json()['id']
    audit_id=execute('''INSERT INTO audits(institution_id,filename,storage_path,filetype,status,created_at,created_by)
           VALUES(?,?,?,?,?,?,?)''',(inst,'del-test.docx','', '.docx','complete','2026-11-13',1))
    execute('''INSERT INTO findings(audit_id,requirement_id,code,title,category,status,expected,observed)
            VALUES(?,?,?,?,?,?,?,?)''',(audit_id,rid,'required_policy','Delete test requirement','policy','passed',
                                         'This wording must be included.','This wording must be included.'))
    before=client.get(f'/api/audits/{audit_id}').json()['findings']
    assert any(x['requirement_id']==rid for x in before)
    sid=execute('INSERT INTO source_checks(institution_id,target_type,target_id,url,checked_at,status) VALUES(?,?,?,?,?,?)',
                (inst,'course',cid,'https://college.example.edu/course','2026-11-13','matched'))
    sid2=execute('INSERT INTO source_checks(institution_id,target_type,target_id,url,checked_at,status) VALUES(?,?,?,?,?,?)',
                (inst,'requirement',rid,'https://college.example.edu/policy','2026-11-13','matched'))
    # Non-admin users must never have destructive access.
    account=client.post('/api/users',json={'username':'reference_reviewer','password':'very-secure-reference-test','role':'reviewer'})
    assert account.status_code==200
    with TestClient(main.app) as rv:
        auth=rv.post('/api/login',json={'username':'reference_reviewer','password':'very-secure-reference-test'})
        assert auth.status_code==200
        rv.headers['X-CSRF-Token']=auth.json()['csrf']
        assert rv.delete(f'/api/courses/{cid}').status_code==403
        assert rv.delete(f'/api/requirements/{rid}').status_code==403
        assert rv.request('DELETE','/api/courses/all',json={'institution_id':inst,'expected_count':1,'confirmation':'DELETE ALL'}).status_code==403
    assert client.delete(f'/api/courses/{cid}').status_code==200
    assert client.delete(f'/api/requirements/{rid}').status_code==200
    assert client.delete(f'/api/courses/{cid}').status_code==404
    assert client.delete(f'/api/requirements/{rid}').status_code==404
    assert one('SELECT * FROM source_checks WHERE id=?',(sid,)) is None
    assert one('SELECT * FROM source_checks WHERE id=?',(sid2,)) is None
    after=client.get(f'/api/audits/{audit_id}').json()['findings']
    assert len(after)==len(before)
    matching=next(x for x in after if x['title']=='Delete test requirement')
    assert matching['requirement_id'] is None
    assert matching['expected']=='This wording must be included.'


def test_delete_template_disables_scoped_requirements_and_preserves_history(client):
    inst=client.get('/api/institutions').json()[0]['id']
    resp=client.post('/api/templates/upload',data={'institution_id':inst,'name':'Delete test template'},
                      files={'file':('template.docx',make_doc(['Required section.']),'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
    assert resp.status_code==200,resp.text
    tid=resp.json()['id']
    template=one('SELECT * FROM templates WHERE id=?',(tid,))
    path=Path(template['doc_path']);assert path.is_file()
    rid=execute('''INSERT INTO requirements(institution_id,template_id,name,expected_text,created_at,updated_at)
            VALUES(?,?,?,?,?,?)''',(inst,tid,'Template-only policy','Template only wording','2026-11-13','2026-11-13'))
    job_id=execute('''INSERT INTO audit_jobs(institution_id,template_id,created_by,created_at,status)
             VALUES(?,?,?,?,?)''',(inst,tid,1,'2026-11-13','complete'))
    audit_id=execute('''INSERT INTO audits(job_id,institution_id,template_id,filename,storage_path,filetype,status,created_at,created_by)
            VALUES(?,?,?,?,?,?,?,?,?)''',(job_id,inst,tid,'template-audit.docx','','.docx','complete','2026-11-13',1))
    assert one('SELECT template_id FROM audits WHERE id=?',(audit_id,))['template_id']==tid
    result=client.delete(f'/api/templates/{tid}')
    assert result.status_code==200,result.text
    assert result.json()['disabled_linked_policies']==1
    assert one('SELECT * FROM templates WHERE id=?',(tid,)) is None
    assert not path.exists()
    rule=one('SELECT template_id,active FROM requirements WHERE id=?',(rid,))
    assert rule=={'template_id':None,'active':0}
    assert one('SELECT template_id FROM audits WHERE id=?',(audit_id,))['template_id'] is None
    assert one('SELECT template_id FROM audit_jobs WHERE id=?',(job_id,))['template_id'] is None
    assert client.get(f'/api/audits/{audit_id}/report.pdf').status_code==200
    assert client.delete(f'/api/templates/{tid}').status_code==404
    assert client.delete(f'/api/requirements/{rid}').status_code==200


def test_delete_template_blocked_during_active_audit(client):
    inst=client.get('/api/institutions').json()[0]['id']
    resp=client.post('/api/templates/upload',data={'institution_id':inst,'name':'Busy template'},
                     files={'file':('busy.docx',make_doc(['Busy policy.']),'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
    tid=resp.json()['id']
    jid=execute("""INSERT INTO audit_jobs(institution_id,template_id,created_by,created_at,status)
           VALUES(?,?,?,?,?)""",(inst,tid,1,'2026-11-13','running'))
    assert client.delete(f'/api/templates/{tid}').status_code==409
    assert one('SELECT id FROM templates WHERE id=?',(tid,))
    execute('UPDATE audit_jobs SET status="complete" WHERE id=?',(jid,))
    assert client.delete(f'/api/templates/{tid}').status_code==200


def test_delete_all_courses_double_confirmation_count_and_institution_scope(client):
    inst=client.get('/api/institutions').json()[0]['id']
    new=client.post('/api/institutions',json={'name':'Other Institution','academic_year':'2026-2027'})
    assert new.status_code==200,new.text
    second=new.json()['id']
    course=client.post('/api/courses',json={'institution_id':second,'code':'HIS-301','title':'Independent history','academic_year':'2026-2027'})
    assert course.status_code==200
    count=one('SELECT COUNT(*) n FROM courses WHERE institution_id=?',(inst,))['n']
    bad=client.request('DELETE','/api/courses/all',json={'institution_id':inst,'expected_count':count})
    assert bad.status_code==400
    bad=client.request('DELETE','/api/courses/all',json={'institution_id':inst,'expected_count':count,'confirmation':'delete all'})
    assert bad.status_code==400
    bad=client.request('DELETE','/api/courses/all',json={'institution_id':inst,'expected_count':count+1,'confirmation':'DELETE ALL'})
    assert bad.status_code==409
    assert one('SELECT COUNT(*) n FROM courses WHERE institution_id=?',(inst,))['n']==count
    pending=execute('''INSERT INTO catalog_imports(institution_id,created_by,seed_url,created_at,status)
         VALUES(?,?,?,?,?)''',(inst,1,'https://college.example.edu/','2026-11-13','running'))
    blocked=client.request('DELETE','/api/courses/all',json={'institution_id':inst,'expected_count':count,'confirmation':'DELETE ALL'})
    assert blocked.status_code==409
    execute('UPDATE catalog_imports SET status="failed" WHERE id=?',(pending,))
    deleted=client.request('DELETE','/api/courses/all',json={'institution_id':inst,'expected_count':count,'confirmation':'DELETE ALL'})
    assert deleted.status_code==200,deleted.text
    assert deleted.json()['deleted']==count
    assert client.get('/api/courses',params={'institution_id':inst}).json()==[]
    assert len(client.get('/api/courses',params={'institution_id':second}).json())==1
    assert client.get('/api/audits',params={'institution_id':inst}).status_code==200
