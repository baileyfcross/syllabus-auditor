"""Bounded catalog discovery with explicit, auditable bulk import approval.

No AI provider, API key, or separate service is used.  Records are suggestions until
an administrator approves importing them, and then remain unverified until the
normal official-source verification succeeds.
"""
import json
import re
import time
from collections import deque
from bs4 import BeautifulSoup
from urllib.parse import urldefrag, urlsplit, parse_qs, urlencode, urlunsplit

from .database import all_rows, execute, now, one, record_revision, transaction
from .sources import fetch_source, validate_url, _allowed_hosts

# Restrict crawl size and extraction to avoid overwhelming public catalogs or the server.
MAX_PAGES = 3500
MAX_COURSES = 6000
COURSE_CODE = re.compile(r'\b([A-Z]{2,5})[\s-]?(\d{3,4}[A-Z]?)\b')
HEADING = re.compile(r'^\s*([A-Z]{2,6})[\s-]?(\d{2,4}[A-Z]?)\s*(?:[-–—:]\s*|\s+)(\S.{2,180})\s*$', re.I)
CREDIT = re.compile(r'(?:\b(?:credits?|credit hours)\s*:?\s*(\d+(?:\.\d+)?)\b|\b(\d+(?:\.\d+)?)\s*(?:credits?|credit hours)\b)',re.I)
PREREQUISITE = re.compile(r'^(?:prerequisites?|pre-requisites?|prerequisite\(s\))\s*:?\s*(.*)$',re.I)
STOPWORDS = re.compile(r'^(?:Back to Top|Add to Favorites|Catalog Navigation|Print this Page|Course Descriptions|Course Search|Go to Top|Return to|Powered by|Click here|University Catalog|College Catalog)$',re.I)
LINK_TERMS = ('course','catalog','prefix','subject','discipline','curriculum','department','page=','filter','az=')


def _catalog_id(url):
    """Acalog uses catoid for plain listings and cur_cat_oid for filtered ones."""
    query = parse_qs(urlsplit(url).query)
    return (query.get('catoid') or query.get('cur_cat_oid') or [''])[0]


def _subject_filter(url):
    query = parse_qs(urlsplit(url).query)
    return (query.get('filter[27]') or query.get('subjects') or [''])[0].strip().upper()


def _self_service(url):
    """Only identify the institution's public Ellucian course search pages."""
    path = urlsplit(url).path.rstrip('/').lower()
    return path.endswith('/student/courses') or path.endswith('/student/courses/search')


def _capture_source_compatible(seed_url, source_url):
    a, b = urlsplit(seed_url), urlsplit(source_url)
    if a.hostname != b.hostname or b.scheme != 'https' or b.username or b.password or b.port not in (None, 443):
        return False
    if _self_service(seed_url):
        return _self_service(source_url) and (not _subject_filter(seed_url) or
            _subject_filter(seed_url) == _subject_filter(source_url))
    return bool(_catalog_id(seed_url) and _catalog_id(source_url) == _catalog_id(seed_url))


def canonical_code(s):
    match = COURSE_CODE.search(s.upper())
    return (f'{match.group(1)}-{match.group(2)}' if match else '')


def _clean(value):
    return ' '.join(str(value).replace('\xa0',' ').split())


def _relevant_link(link, base):
    """Crawl course details and same-catalog course listings, not the whole school site."""
    url=link['url'];label=link.get('label','').strip().lower()
    target=urlsplit(url);seed=urlsplit(base)
    if target.scheme!='https' or not target.hostname:return False
    if url.lower().endswith(('.zip','.docx','.jpg','.png','.svg','.mp4')):return False
    if target.hostname != seed.hostname:return False
    params=parse_qs(target.query);scope=parse_qs(seed.query)
    # Acalog: never cross from the selected 2026-27 catalog into older catalogs.
    if _catalog_id(base) and _catalog_id(url) and _catalog_id(url)!=_catalog_id(base):return False
    if _subject_filter(base) and target.path.lower().endswith('/content.php'):
        if _subject_filter(url)!=_subject_filter(base):return False
    if 'preview_course' in target.path.lower():return 'coid' in params
    if target.path.lower().endswith('/content.php') and 'navoid' in scope:
        # Acalog has dozens of unrelated catalog content pages with different navoid.
        return params.get('navoid')==scope['navoid']
    if _catalog_id(base) and target.path.lower().endswith('/courses.php'):
        return bool(params.get('catoid'))
    # Generic college catalogs may use directory-style course detail URLs.
    text=(target.path+'?'+target.query+' '+label).lower()
    return bool(COURSE_CODE.search(label.upper()) or any(term in text for term in LINK_TERMS))


def _field_lines(lines):
    """Extract tagged metadata without making assumptions about catalog templates."""
    credits='';pre=''
    for line in lines[:30]:
        if not credits:
            m=CREDIT.search(line)
            if m:credits=(m.group(1) or m.group(2) or '')
        if not pre:
            m=PREREQUISITE.match(line)
            if m:pre=m.group(1).strip()[:500]
    return credits,pre


def _extract(text, url):
    """Find complete or partial course entries from text and return traceable evidence."""
    lines=[_clean(x) for x in text.splitlines()]
    found=[];starts=[]
    for pos,line in enumerate(lines):
        m=HEADING.match(line)
        if m and not STOPWORDS.match(m.group(3)):
            title=m.group(3).strip(' -:')
            if len(title)>=4 and len(title)<=180:
                starts.append((pos,f'{m.group(1).upper()}-{m.group(2).upper()}',title))
    for i,(at,code,title) in enumerate(starts):
        end=starts[i+1][0] if i+1<len(starts) else len(lines)
        # A listing with one paragraph per course can hold many entries.
        body=[x for x in lines[at+1:min(at+55,end)] if x and not STOPWORDS.match(x)]
        # Avoid accepting generic navigation or another course title as a description.
        body=[x for x in body if not re.match(r'^(?:Show Prefix List|Courses|Programs|Search|Home|Catalog Search|Print)',x,re.I)]
        credits,pre=_field_lines(body)
        descr=[]
        for line in body:
            if len(' '.join(descr))>2400:break
            if PREREQUISITE.match(line):continue
            if CREDIT.fullmatch(line) or re.match(r'^\d+(?:\.\d+)?\s+(?:Credit|Lab|Lecture) Hours?$',line,re.I):continue
            if re.match(r'^(?:Co-?requisites?|Typically Offered|Course Type|Repeatable|Grading Basis)\s*:',line,re.I):continue
            if len(line)<18 and len(body)>2:continue
            descr.append(line)
        description=_clean(' '.join(descr))[:2400]
        # Many listing pages include a course heading followed by only navigation.
        if len(description)<36:description=''
        found.append({'code':code,'title':title,'description':description,'credits':credits,
                      'prerequisites':pre,'source_url':url,'evidence':_clean(' '.join(lines[at:min(end,at+9)]))[:900]})
    return found


def _link_candidates(links, base):
    """Keep course listings as partial candidates if the detail pages cannot be parsed."""
    out=[]
    for link in links:
        title=link.get('label','')
        m=HEADING.match(title)
        if m:
            code=f'{m.group(1).upper()}-{m.group(2).upper()}'
            out.append({'code':code,'title':m.group(3).strip(), 'description':'', 'credits':'',
                        'prerequisites':'','source_url':link['url'],'evidence':title[:500]})
    return out


def _acalog_urls(page, seed):
    """Turn Acalog's GET filter form into discoverable, scoped listing pages.

    Many Acalog installations submit filters via a form instead of <a> links.
    A query string with only catoid/navoid therefore has no crawlable course links.
    Never guess course IDs and never leave the administrator's chosen catalog year.
    """
    parsed=urlsplit(seed);q=parse_qs(parsed.query)
    if not parsed.path.lower().endswith('/content.php') or not _catalog_id(seed) or not q.get('navoid'):
        return []
    html=page.get('html','')
    if not html and not _subject_filter(seed):return []
    soup=BeautifulSoup(html or '', 'html.parser')
    selectors=soup.find_all('select',attrs={'name':re.compile(r'^filter\[27\]$')})
    if not selectors and not _subject_filter(seed):
        # This is often a branded 200 response from a WAF, not the real listing.
        return []
    prefixes=[]
    for select in selectors:
        for option in select.find_all('option'):
            value=str(option.get('value','')).strip()
            if value and value not in ('-1','0','all','All') and re.fullmatch(r'[A-Za-z0-9 &/-]{2,16}',value):
                if value not in prefixes:prefixes.append(value)
    def listing(prefix):
        id_key='catoid' if q.get('catoid') else 'cur_cat_oid'
        params=[(id_key,_catalog_id(seed)),('navoid',q['navoid'][0]),
                ('filter[27]',prefix),('filter[29]',''),('filter[course_type]','-1'),
                ('filter[keyword]',''),('filter[32]','1'),('filter[cpage]','1'),
                ('search_database','Filter'),('filter[exact_match]','1')]
        return urlunsplit((parsed.scheme,parsed.netloc,parsed.path,urlencode(params),''))
    # Explicit prefixes avoid a site-specific "all" filter that might fail.
    selected=_subject_filter(seed)
    return [listing(selected)] if selected else ([listing(prefix) for prefix in prefixes[:200]] or [listing('-1')])


def _acalog_pagination_urls(page, url, seed):
    """Discover Acalog's numbered filter pages when page-number links are absent."""
    part=urlsplit(url);query=parse_qs(part.query)
    scope=parse_qs(urlsplit(seed).query)
    if not part.path.lower().endswith('/content.php'):
        return []
    if not query.get('filter[27]') or _catalog_id(url)!=_catalog_id(seed) or query.get('navoid')!=scope.get('navoid'):
        return []
    # Only expand the first page of each prefix; prevent duplicate frontier growth.
    if query.get('filter[cpage]',['1'])[0] != '1':return []
    html=page.get('html','')
    if not html:return []
    soup=BeautifulSoup(html,'html.parser')
    numbers=set()
    for select in soup.find_all('select',attrs={'name':'filter[cpage]'}):
        for option in select.find_all('option'):
            val=str(option.get('value','')).strip()
            if val.isdigit():numbers.add(int(val))
    if not numbers:
        # Some catalogs render 'Page 1 of 10' as plain text rather than links.
        m=re.search(r'\bPage\s+1\s+of\s+(\d{1,3})\b',_clean(page.get('text','')),re.I)
        if m:numbers.update(range(2,min(int(m.group(1)),150)+1))
    urls=[]
    for num in sorted(n for n in numbers if 2<=n<=150):
        new_query=[(k,v) for k,values in query.items() for v in values if k!='filter[cpage]']
        new_query.append(('filter[cpage]',str(num)))
        urls.append(urlunsplit((part.scheme,part.netloc,part.path,urlencode(new_query),'')))
    return urls


def _is_empty_or_blocked(page):
    text=_clean(page.get('text','')).lower()
    hints=('access denied','verify you are human','enable javascript and cookies',
           'request blocked','bot protection','captcha','checking your browser',
           'this website is using a security service')
    return any(hint in text[:1500] for hint in hints)


def _detail_link_candidate(link):
    """Keep a course code-only Acalog link if the detail page is unavailable."""
    target=urlsplit(link['url'])
    if 'preview_course' not in target.path.lower() or not parse_qs(target.query).get('coid'):
        return None
    label=_clean(link.get('label',''))
    m=COURSE_CODE.search(label.upper())
    if not m:return None
    code=f'{m.group(1)}-{m.group(2)}'
    remainder=label[m.end():].strip(' :-–—')
    return {'code':code,'title':remainder[:180],'description':'','credits':'',
            'prerequisites':'','source_url':link['url'],'evidence':label[:500]}


def _merge_course(best,item):
    code=item['code']
    previous=best.get(code)
    if previous is None or _weight(item)>_weight(previous):
        best[code]=item


def _acalog_heading_recovery(page):
    """Preview pages sometimes split the code and title into separate HTML lines."""
    lines=[_clean(line) for line in page.get('text','').splitlines() if _clean(line)]
    results=[]
    for i,line in enumerate(lines):
        m=re.fullmatch(r'([A-Z]{2,5})[ -](\d{3,4}[A-Z]?)',line,re.I)
        if not m or i+2>=len(lines):continue
        title=lines[i+1]
        if not 4<=len(title)<=180 or COURSE_CODE.search(title.upper()):continue
        code=f'{m.group(1).upper()}-{m.group(2).upper()}'
        snippet='\n'.join([f'{code} - {title}',*lines[i+2:i+60]])
        results+=_extract(snippet,page['url'])
    return results


def _weight(item):
    return (bool(item['description']),len(item['description']),bool(item['credits']),bool(item['prerequisites']))


def _save_progress(ident,**kwargs):
    with transaction() as db:
        db.execute('UPDATE catalog_imports SET '+','.join(f'{key}=?' for key in kwargs)+' WHERE id=?',(*kwargs.values(),ident))


def _store_scan_results(ident, institution, job, best, pages, partial, failures):
    """Stage discovered records for admin review, never auto-approve."""
    if not best:
        raise ValueError('No usable course records discovered; scan is not ready. '+ '; '.join(failures[:2]))
    with transaction() as db:
        for item in sorted(best.values(),key=lambda x:x['code']):
            existing=db.execute('SELECT * FROM courses WHERE institution_id=? AND code=? AND academic_year=?',
                               (institution['id'],item['code'],job['academic_year'])).fetchone()
            if existing:
                old=dict(existing)
                status='unchanged' if all(old[k]==item[k] for k in ['title','description','credits','prerequisites','source_url'] if item[k]) else 'changed'
            else: status='new' if item['description'] else 'incomplete'
            db.execute('''INSERT INTO catalog_import_items(import_id,code,title,description,credits,prerequisites,source_url,evidence,status)
                         VALUES(?,?,?,?,?,?,?,?,?)''',(ident,item['code'],item['title'],item['description'],item['credits'],item['prerequisites'],item['source_url'],item['evidence'],status))
        db.execute('UPDATE catalog_imports SET status=?,pages_scanned=?,courses_found=?,finished_at=?,truncated=?,errors_json=? WHERE id=?',
            ('ready',pages,len(best),now(),int(partial),json.dumps(failures),ident))


def scan_myocc_catalog(ident, institution, job):
    """Collect a dynamic MyOCC course listing in the local headless browser."""
    from .myocc_bulk import collect_myocc
    seed=job['seed_url']
    validate_url(seed,institution)
    subjects=[x.strip().upper() for x in (job.get('subject_codes') or '').split(',') if x.strip()]
    def progress(pages,count):_save_progress(ident,pages_scanned=pages,courses_found=count)
    records,pages,partial,warnings=collect_myocc(seed,institution,subjects,
                                                  min(job['max_pages'],MAX_PAGES),progress)
    best={}
    for record in records:_merge_course(best,record)
    _store_scan_results(ident,institution,job,best,pages,partial,warnings)


def scan_catalog(ident,institution):
    """Background scan. A bounded official-site crawl, not a claim of total coverage."""
    job=one('SELECT * FROM catalog_imports WHERE id=?',(ident,))
    if not job:return
    seed=job['seed_url'];limit=min(job['max_pages'],MAX_PAGES)
    try:
        if _self_service(seed):
            scan_myocc_catalog(ident,institution,job)
            return
        validate_url(seed,institution)
        queue=deque([seed]);seen=set();best={};failures=[];pages_ok=0
        approved_hosts=_allowed_hosts(institution)
        catalog_host=urlsplit(seed).hostname
        first_page_note=''
        while queue and len(seen)<limit and len(best)<MAX_COURSES:
            url=queue.popleft()
            if url in seen:continue
            seen.add(url)
            try:
                page=fetch_source(url,institution)
            except Exception as e:
                if len(failures)<12:failures.append(f'{url}: {str(e)[:150]}')
                _save_progress(ident,pages_scanned=len(seen),courses_found=len(best))
                continue
            pages_ok+=1
            if pages_ok==1:
                first_page_note=_clean(page.get('text',''))[:180]
            if _is_empty_or_blocked(page):
                if len(failures)<12:failures.append(f'{url}: server returned an access-denied or bot-check page')
                _save_progress(ident,pages_scanned=len(seen),courses_found=len(best))
                continue
            for item in _extract(page['text'],page['url'])+_acalog_heading_recovery(page)+_link_candidates(page['links'],page['url']):
                if not _subject_filter(seed) or item['code'].split('-')[0]==_subject_filter(seed):
                    _merge_course(best,item)
            for link in page['links']:
                item=_detail_link_candidate(link)
                if item and (not _subject_filter(seed) or item['code'].split('-')[0]==_subject_filter(seed)):_merge_course(best,item)
            # List all course prefixes before fetching their individual detail pages.
            # This prevents the page limit being consumed by the first department.
            candidates=_acalog_urls(page,seed) if url==seed else []
            candidates += _acalog_pagination_urls(page,url,seed)
            candidates += [link['url'] for link in page['links'] if _relevant_link(link,seed)]
            for href in candidates:
                href=urldefrag(href)[0]
                if href in seen or href in queue or len(queue)>MAX_COURSES*2:continue
                parsed=urlsplit(href);hostname=(parsed.hostname or '').lower()
                if parsed.username or parsed.password or parsed.port not in (None,443):continue
                if not any(hostname==h or hostname.endswith('.'+h) for h in approved_hosts):continue
                # Never follow a catalog listing into another catalog year.
                if hostname==catalog_host and not _relevant_link({'url':href,'label':''},seed):continue
                queue.append(href)
            _save_progress(ident,pages_scanned=len(seen),courses_found=len(best))
            time.sleep(0.08)
        if pages_ok==0:
            raise ValueError('Catalog could not be retrieved. The site may block automated access. '+('; '.join(failures[:2])))
        if not best:
            message=('No course records were found. This catalog may require form-based navigation, '
                     'may have blocked the automated request, or returned a page without course data. '
                     'The scan cannot be marked ready. ')
            message+=('First page text: '+first_page_note[:120]+'; ') if first_page_note else ''
            message+='; '.join(failures[:2])
            raise ValueError(message[:1200])
        _store_scan_results(ident,institution,job,best,len(seen),
                            bool(queue) or len(best)>=MAX_COURSES,failures)
    except Exception as exc:
        _save_progress(ident,status='failed',error=str(exc)[:1200],finished_at=now())


def apply_import(ident, actor, update_existing=False):
    """Only explicit administrator action alters authoritative course reference records."""
    with transaction() as db:
        job=db.execute('SELECT * FROM catalog_imports WHERE id=?',(ident,)).fetchone()
        if not job:raise ValueError('Import not found')
        if job['status'] not in ('ready','applied'):raise ValueError('Catalog scan is not ready for approval')
        rows=db.execute('SELECT * FROM catalog_import_items WHERE import_id=? ORDER BY id',(ident,)).fetchall()
        created=updated=unchanged=skipped=0
        for row in rows:
            row=dict(row)
            if not row['description']:
                skipped+=1;continue
            old=db.execute('SELECT * FROM courses WHERE institution_id=? AND code=? AND academic_year=?',
                (job['institution_id'],row['code'],job['academic_year'])).fetchone()
            if old is None:
                db.execute('''INSERT INTO courses(institution_id,code,title,description,credits,prerequisites,academic_year,source_url,created_at)
                              VALUES(?,?,?,?,?,?,?,?,?)''',(job['institution_id'],row['code'],row['title'],row['description'],row['credits'],row['prerequisites'],job['academic_year'],row['source_url'],now()))
                created+=1
            elif update_existing:
                before=dict(old);changes={k:row[k] for k in ('title','description','credits','prerequisites','source_url') if row[k] and row[k]!=old[k]}
                if changes:
                    db.execute('UPDATE courses SET '+','.join(f'{k}=?' for k in changes)+',version=version+1,last_verified_at="" WHERE id=?',(*changes.values(),old['id']))
                    db.execute('INSERT INTO revisions(kind,target_id,actor_id,old_json,new_json,changed_at) VALUES(?,?,?,?,?,?)',
                        ('course',old['id'],actor,json.dumps(before),json.dumps(changes),now()))
                    updated+=1
                else:unchanged+=1
            else:skipped+=1
        db.execute('UPDATE catalog_imports SET status=? WHERE id=?',('applied',ident))
        db.execute('INSERT INTO activity(actor_id,verb,target,detail,created_at) VALUES(?,?,?,?,?)',
            (actor,'catalog.bulk_import',str(ident),f'created={created}; updated={updated}; unchanged={unchanged}; skipped={skipped}',now()))
    return {'created':created,'updated':updated,'unchanged':unchanged,'skipped':skipped,'unverified':True}


def create_browser_capture_import(institution, actor_id, academic_year, seed_url, payload_bytes, filename):
    """Stage a public catalog captured in the user's own browser for human approval.

    This is intentionally NOT a verified-source check: uploaded content is untrusted,
    and course descriptions remain unverified until independent source verification.
    """
    from urllib.parse import urlsplit
    if len(payload_bytes) > 20_000_000:
        raise ValueError('Catalog capture exceeds 20 MB')
    seed_url = str(seed_url or '').strip()
    base = urlsplit(seed_url)
    approved = _allowed_hosts(institution)
    if (base.scheme != 'https' or not base.hostname or base.username or base.password
            or base.port not in (None, 443)
            or not any(base.hostname == h or base.hostname.endswith('.' + h) for h in approved)):
        raise ValueError('The capture source must be an approved HTTPS catalog host')
    academic_year = str(academic_year or '').strip()[:30]
    if not re.fullmatch(r'20\d\d\s*[-–/]\s*20\d\d', academic_year):
        raise ValueError('Enter a full catalog year, such as 2026-2027')
    errors = []
    pages_checked = 1
    complete = False
    candidate_rows = []
    skipped_rows = 0
    if filename.lower().endswith('.json'):
        try:
            payload = json.loads(payload_bytes.decode('utf-8-sig'))
        except (ValueError, UnicodeError) as exc:
            raise ValueError('Invalid catalog JSON export') from exc
        if not isinstance(payload, dict) or not isinstance(payload.get('courses'), list):
            raise ValueError('Expected a catalog export JSON object with a courses array')
        source = str(payload.get('source_url') or '')
        source_parts = urlsplit(source)
        if not _capture_source_compatible(seed_url, source):
            raise ValueError('Capture belongs to a different catalog hostname or catalog year')
        complete = payload.get('complete') is True
        pages_checked = min(3500, max(1, int(payload.get('pages_checked') or 1)))
        errors = [str(e)[:240] for e in payload.get('errors', [])[:30] if isinstance(e, str)] if isinstance(payload.get('errors'), list) else []
        for row in payload['courses'][:MAX_COURSES]:
            if not isinstance(row, dict):
                skipped_rows += 1
                continue
            code = canonical_code(str(row.get('code', '')).upper())
            title = _clean(row.get('title', ''))[:180]
            description = _clean(row.get('description', ''))[:5000]
            credits = _clean(row.get('credits', ''))[:30]
            prerequisites = _clean(row.get('prerequisites', ''))[:800]
            source_url = str(row.get('source_url') or seed_url)
            parts = urlsplit(source_url)
            if (parts.scheme != 'https' or parts.hostname != base.hostname
                    or parts.username or parts.password or parts.port not in (None,443)):
                skipped_rows += 1
                continue
            if _self_service(seed_url) and not _self_service(source_url):
                skipped_rows += 1
                continue
            if _catalog_id(source_url) and _catalog_id(source_url) != _catalog_id(seed_url):
                skipped_rows += 1
                continue
            if not code or not title or (_subject_filter(seed_url) and code.split('-')[0]!=_subject_filter(seed_url)):
                skipped_rows += 1
            if code and title and (not _subject_filter(seed_url) or code.split('-')[0]==_subject_filter(seed_url)):
                candidate_rows.append({'code':code,'title':title,'description':description,
                                       'credits':credits,'prerequisites':prerequisites,'source_url':source_url,
                                       'evidence':_clean(row.get('evidence', ''))[:900]})
        if len(payload['courses']) > MAX_COURSES:
            complete = False
            errors.append('The capture exceeds the maximum 6,000 course entries')
    elif filename.lower().endswith(('.html', '.htm')):
        soup = BeautifulSoup(payload_bytes, 'html.parser')
        for bad in soup(['script', 'style', 'noscript']):
            bad.decompose()
        for block in soup.select('.courseblock, .acalog-course, .acalog-course-container, .course_block, .course-container')[:MAX_COURSES]:
            title_el = block.select_one('.courseblocktitle, .acalog-course-header, .course-title, .course_header, h2, h3, h4, strong, a')
            if title_el is None: continue
            title = _clean(title_el.get_text(' ',strip=True))
            m = HEADING.match(title)
            if not m: continue
            code = f'{m.group(1).upper()}-{m.group(2).upper()}'
            desc = block.select_one('.courseblockdesc, .acalog-course-description, .course-description, .course-desc')
            description = _clean(desc.get_text(' ',strip=True))[:5000] if desc else ''
            if not description:
                text = _clean(block.get_text(' ', strip=True))
                description = text[len(title):].strip(' -:')[:5000] if text.startswith(title) else ''
            description = re.sub(r'^\d+(?:\.\d+)?\s*(?:credit\s+hours?|credits?)\s*', '', description, flags=re.I)
            credits,pre = _field_lines(block.get_text('\n',strip=True).splitlines())
            candidate_rows.append({'code':code,'title':m.group(3).strip(),'description':description,
                'credits':credits,'prerequisites':pre,'source_url':seed_url,'evidence':title})
        text = soup.get_text('\n', strip=True)
        candidate_rows += _extract(text, seed_url)
        anchors = [{'url':seed_url,'label':a.get_text(' ',strip=True)} for a in soup.select('a[href]')]
        candidate_rows += _link_candidates(anchors, seed_url)
        errors = ['Saved HTML can contain only the currently visible catalog page. Use the browser capture script for all subjects and pages.']
    else:
        raise ValueError('Upload a .json browser catalog capture or saved .html page')
    best = {}
    for row in candidate_rows:
        if _subject_filter(seed_url) and row['code'].split('-')[0]!=_subject_filter(seed_url):
            skipped_rows += 1
            continue
        _merge_course(best, row)
    if not best:
        raise ValueError('No recognizable course codes were found in the uploaded catalog export')
    if not any(c['description'] and len(c['description']) >= 24 for c in best.values()):
        raise ValueError('Course codes were found, but no descriptions. Capture expanded course descriptions or use the browser capture script.')
    incomplete=sum(len(c['description'])<24 for c in best.values())
    if skipped_rows:
        errors.append(f'{skipped_rows} invalid or out-of-scope course entries were skipped')
    if incomplete:
        errors.append(f'{incomplete} entries lack complete descriptions')
    complete = bool(complete and not errors and not skipped_rows and not incomplete)
    with transaction() as db:
        cursor = db.execute('''INSERT INTO catalog_imports
            (institution_id,created_by,seed_url,academic_year,status,max_pages,pages_scanned,courses_found,truncated,errors_json,created_at,finished_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
            (institution['id'],actor_id,seed_url,academic_year,'ready',MAX_PAGES,pages_checked,
             len(best),int(not complete),json.dumps(errors),now(),now()))
        ident = cursor.lastrowid
        for item in sorted(best.values(), key=lambda x: x['code']):
            existing = db.execute('SELECT * FROM courses WHERE institution_id=? AND code=? AND academic_year=?',
                                  (institution['id'],item['code'],academic_year)).fetchone()
            if not item['description']:
                status = 'incomplete'
            elif existing:
                old = dict(existing)
                status = ('unchanged' if all(old[k] == item[k] for k in
                     ['title','description','credits','prerequisites','source_url'] if item[k]) else 'changed')
            else:
                status = 'new'
            db.execute('''INSERT INTO catalog_import_items
              (import_id,code,title,description,credits,prerequisites,source_url,evidence,status)
              VALUES(?,?,?,?,?,?,?,?,?)''',(ident,item['code'],item['title'],item['description'],
                 item['credits'],item['prerequisites'],item['source_url'],item['evidence'],status))
    return {'id':ident,'status':'ready','courses_found':len(best),'complete':complete,
            'pages_checked':pages_checked,'warnings':errors}
