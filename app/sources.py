"""Constrained official-source retrieval, change proposals, and bounded catalog discovery."""
import ipaddress, socket, re, html, urllib.parse, json
from datetime import datetime, timezone
import httpx
from bs4 import BeautifulSoup
import fitz
from .database import one, all_rows, execute, now

MAX_SOURCE_BYTES=3_000_000

def _allowed_hosts(institution):
    out=set()
    for u in [institution.get('catalog_url','')]:
        try:
            hostname=urllib.parse.urlsplit(u).hostname
            if hostname: out.add(hostname.lower())
        except ValueError: pass
    for h in (institution.get('allowed_hosts','') or '').replace(';',',').split(','):
        h=h.strip().lower()
        if h and re.fullmatch(r'[a-z0-9.-]+',h): out.add(h)
    return out

def validate_url(url,institution):
    try: p=urllib.parse.urlsplit(url)
    except ValueError: raise ValueError('Invalid URL')
    if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443):
        raise ValueError('Only HTTPS public websites are supported')
    hosts=_allowed_hosts(institution)
    if not hosts: raise ValueError('Configure an official catalog URL or an approved host first')
    if not any(p.hostname.lower()==h or p.hostname.lower().endswith('.'+h) for h in hosts):
        raise ValueError('URL is outside the institution approved domains')
    try: answers=socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM)
    except OSError as e: raise ValueError('Official source host could not be resolved') from e
    if not answers: raise ValueError('Host has no address')
    for a in answers:
        ip=ipaddress.ip_address(a[4][0])
        if not ip.is_global: raise ValueError('Private or nonpublic source addresses are prohibited')
    return True

def fetch_source(url,institution):
    """HTTPS only; validated hostname and each redirect, modest resource limits."""
    with httpx.Client(timeout=httpx.Timeout(12,connect=6),follow_redirects=False,
                      headers={'User-Agent':'SyllabusAuditor/1.0 (+institutional-verification)'},trust_env=False) as client:
        for _ in range(5):
            validate_url(url,institution)
            with client.stream('GET',url) as resp:
                if resp.status_code in (301,302,303,307,308):
                    location=resp.headers.get('location','')
                    if not location: raise ValueError('Redirect missing location')
                    url=urllib.parse.urljoin(url,location)
                    continue
                resp.raise_for_status()
                content_type=resp.headers.get('content-type','')
                if not any(x in content_type for x in ('html','text/','pdf','application/octet-stream')):
                    raise ValueError('Source is not HTML, text, or PDF')
                chunks=[];size=0
                for chunk in resp.iter_bytes():
                    size+=len(chunk)
                    if size>MAX_SOURCE_BYTES: raise ValueError('Source page exceeds size limit')
                    chunks.append(chunk)
                data=b''.join(chunks)
                break
        else: raise ValueError('Too many redirects')
    if data.startswith(b'%PDF') or 'pdf' in content_type:
        pdf=fitz.open(stream=data,filetype='pdf')
        with pdf: text='\n'.join(pdf[i].get_text('text') for i in range(min(70,len(pdf))))[:100_000]
        links=[]
    elif 'html' in content_type or b'<html' in data[:500].lower():
        soup=BeautifulSoup(data,'html.parser')
        # Discover navigation links *before* stripping boilerplate from the text.
        links=[]
        for a in soup.find_all('a',href=True)[:500]:
            href=urllib.parse.urljoin(url,a['href']).split('#')[0]
            if href.startswith('https://'):
                links.append({'url':href,'label':a.get_text(' ',strip=True)[:120]})
        for bad in soup(['script','style','nav','footer','header','noscript']):bad.decompose()
        main=soup.find('main') or soup.find('article') or soup.body or soup
        text=main.get_text('\n',strip=True)[:100_000]
    else:
        text=data.decode('utf-8','replace')[:100_000];links=[]
    return {'url':url,'text':text,'links':links,'content_type':content_type}

def _context(text,needle,limit=1700):
    if not needle: return text[:limit]
    match=re.search(re.escape(needle),text,re.I)
    if not match: return text[:limit]
    start=max(0,match.start()-180)
    return text[start:start+limit]

def discover_course(institution,code,steps=20):
    """Bounded crawl of official domain; result is a human-reviewable candidate, not auto-approved."""
    seed=institution.get('catalog_url','')
    if not seed: raise ValueError('Catalog URL not configured')
    validate_url(seed,institution)
    queue=[seed];visited=set(); candidates=[]
    terms=set(re.findall(r'[a-z0-9]+',code.lower()))
    while queue and len(visited)<steps:
        url=queue.pop(0)
        if url in visited:continue
        visited.add(url)
        try: page=fetch_source(url,institution)
        except Exception:continue
        needle=re.sub(r'[^a-z0-9]','',code.lower())
        canonical=re.sub(r'[^a-z0-9]','',page['text'].lower())
        if needle in canonical:
            pos=page['text'].lower().find(code.lower())
            candidate=_context(page['text'],code) if pos>=0 else page['text'][:2200]
            candidates.append({'url':page['url'],'text':candidate,'score':len(terms.intersection(set(page['text'][:500].lower().split())))})
        for link in page['links']:
            if len(queue)>120:break
            href=link['url']; label=link['label'].lower()
            if href in visited or href in queue: continue
            if any(k in label or k in href.lower() for k in [code.lower(),code.lower().replace('-',''), 'course','catalog','curriculum','prefix','search']):
                try: validate_url(href,institution)
                except Exception: continue
                queue.append(href)
    candidates.sort(key=lambda x:x['score'],reverse=True)
    return {'checked_pages':len(visited),'candidates':candidates[:12]}

def check_target(institution,target_type,target_id):
    if target_type=='course':
        target=one('SELECT * FROM courses WHERE id=? AND institution_id=?',(target_id,institution['id']))
        expected=target['description'] if target else ''
        url=target['source_url'] if target else ''
    elif target_type=='requirement':
        target=one('SELECT * FROM requirements WHERE id=? AND institution_id=?',(target_id,institution['id']))
        expected=target['expected_text'] if target else ''
        url=target['source_url'] if target else ''
    else:raise ValueError('Unknown source target')
    if not target: raise ValueError('Item not found')
    if not url: raise ValueError('Item has no official source URL')
    try:
        page=fetch_source(url,institution)
        if not expected.strip():
            status='needs_review'; candidate=page['text'][:1800]
        elif re.sub(r'\s+',' ',expected).strip().lower() in re.sub(r'\s+',' ',page['text']).lower():
            status='verified';candidate=expected
        else:
            status='changed';candidate=_context(page['text'],target['code'] if target_type=='course' else target['name'])
        checked=now()
        ident=execute('INSERT INTO source_checks(institution_id,target_type,target_id,url,checked_at,status,old_text,new_text,evidence) VALUES(?,?,?,?,?,?,?,?,?)',
         (institution['id'],target_type,target_id,page['url'],checked,status,expected,candidate,page['text'][:4000]))
        if status=='verified' and target_type=='course':
            execute('UPDATE courses SET last_verified_at=? WHERE id=?',(checked,target_id))
        return {'id':ident,'status':status,'url':page['url'],'old_text':expected,'new_text':candidate,'checked_at':checked}
    except Exception as exc:
        ident=execute('INSERT INTO source_checks(institution_id,target_type,target_id,url,checked_at,status,old_text,error) VALUES(?,?,?,?,?,?,?,?)',
         (institution['id'],target_type,target_id,url,now(),'unavailable',expected,str(exc)[:600]))
        return {'id':ident,'status':'unavailable','error':str(exc),'url':url}

def refresh_institution(institution):
    result=[]
    for table,key in [('courses','course'),('requirements','requirement')]:
        rows=all_rows(f'SELECT id FROM {table} WHERE institution_id=? AND source_url!=""',(institution['id'],))
        for row in rows:
            result.append(check_target(institution,key,row['id']))
    return result
