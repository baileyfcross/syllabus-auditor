"""Bounded browser-driven bulk discovery of public Ellucian Self-Service course listings.

Uses the institution's public course search in an isolated automated browser. Does not
sign in, use private APIs, bypass access controls, or mark catalog records verified.
"""
import os
import re
from urllib.parse import urlsplit, parse_qs, urlencode, urlunsplit
from .database import one
from .sources import validate_url

SUBJECT = re.compile(r'^[A-Z]{2,6}$')

# Code runs inside the site's *public* rendered page. No credentials/cookies are read.
# Text extraction is intentionally conservative: incomplete entries are staged but
# will not be imported as official course descriptions.
EXTRACT_PAGE_JS = r'''(subject) => {
  const clean = s => String(s || '').replace(/\u00a0/g,' ').replace(/[\t ]+/g,' ').trim();
  const codeRe = /^([A-Z]{2,6})\s*[- ]\s*(\d{2,4}[A-Z]?)\s*(?:[-–—:]\s*|\s+)(.*)$/i;
  const creditRe = /\s*\((\d+(?:\.\d+)?)\s+credits?\)\s*$/i;
  const lines = (document.body.innerText || '').split(/\n+/).map(clean).filter(Boolean);
  const starts = [], unique = new Map();
  const noise = /^(?:Filter Results|Search for Courses|Advanced Search Selection|Filters Applied|No sections match|Table for sections|Instructors|Meeting Information|Dates|Seats Available|Locations?|Offered|Non-Term Section|Book Details|Books Total|Credits|Grading|Transfer Status|Additional Information|Additional Course Fees|Page\s*\d*)\b/i;
  const normalize = s => {
    const m = clean(s).replace(/\s+/g,' ').match(codeRe);
    if (!m) return null;
    const prefix=m[1].toUpperCase();
    if (subject && prefix!==subject) return null;
    let title=clean(m[3]).replace(creditRe, '').trim();
    if (!title || title.length<3 || title.length>180 || /^(?:[\d.\-]+|no description available)$/i.test(title)) return null;
    const credits=clean(m[3]).match(creditRe)?.[1] || '';
    return {code:prefix+'-'+m[2].toUpperCase(),title,credits};
  };
  for(let i=0;i<lines.length;i++){
    let h=normalize(lines[i]);
    if (!h && /^[A-Z]{2,6}[ -]\d{2,4}[A-Z]?$/i.test(lines[i]) && i+1<lines.length) {
      h=normalize(lines[i]+' '+lines[i+1]);
      if(h){starts.push({at:i+1,heading:h});i++;continue;}
    }
    if(h)starts.push({at:i,heading:h});
  }
  function store(heading, body, source) {
    let description='',prerequisites='';
    let readingDescription=false;
    const collected=[];
    for(const raw of body.slice(0,110)) {
      const line=clean(raw);
      if(!line)continue;
      if(/^No description available\.?$/i.test(line)) {collected.length=0; break;}
      if(/^Course Description\s*:?$/i.test(line)) {readingDescription=true;collected.length=0;continue;}
      if(/^Requisites?\s*:?/i.test(line)) {prerequisites=clean(line.replace(/^Requisites?\s*:?/i,'')); if(readingDescription)break;continue;}
      if(noise.test(line) && (readingDescription||collected.length))break;
      if(/^(?:Click for more|show more|more|Hide|View Sections|Section Details|Non-Term Section:|Course Sections)$/i.test(line))continue;
      if(/^\d+(?:\.\d+)?\s+credits?$/i.test(line))continue;
      if(line.length>=8) collected.push(line);
      if(collected.join(' ').length>=5500)break;
    }
    description=clean(collected.join(' ')).slice(0,5000);
    if(description.length<24)description='';
    const item={...heading,description,prerequisites,source_url:source,evidence:clean(heading.code+' '+heading.title+' '+description.slice(0,250))};
    const prev=unique.get(item.code);
    if(!prev||item.description.length>prev.description.length)unique.set(item.code,item);
  }
  for(let i=0;i<starts.length;i++){
    const {at,heading}=starts[i];const end=i+1<starts.length?starts[i+1].at:lines.length;
    store(heading,lines.slice(at+1,Math.min(end,at+110)),location.href);
  }
  // Recover cards where the title and the description are in separate DOM elements.
  for(const title of document.querySelectorAll('h2,h3,h4,h5,[class*="course-title"],[class*="courseTitle"]')) {
    const heading=normalize(title.innerText||'');if(!heading)continue;
    const parent=title.closest('article,li,[class*="course-result"],[class*="courseResult"],section')||title.parentElement;
    if(!parent)continue;
    const local=(parent.innerText||'').split(/\n+/).map(clean).filter(Boolean);
    const at=local.findIndex(x=>normalize(x)?.code===heading.code);
    if(at>=0)store(heading,local.slice(at+1),location.href);
  }
  return {courses:Array.from(unique.values()),headings:starts.length,
          sample:lines.filter(x=>/\b[A-Z]{2,6}\s*[- ]\s*\d{2,4}/i.test(x)).slice(0,5),
          text_excerpt:clean(lines.slice(0,16).join(' ')).slice(0,350)};
}'''

DISCOVER_SUBJECTS_JS = r'''() => {
 const out=new Set();
 for(const e of document.querySelectorAll('a[href*="subjects="],option,[data-subject]')) {
   const href=e.getAttribute('href')||'';
   const code = href ? new URL(href,location.href).searchParams.get('subjects') : (e.dataset.subject || e.value || '');
   const text = (e.textContent||'').trim();
   const match = String(code||'').trim().match(/^[A-Z]{2,6}$/i) || text.match(/\(([A-Z]{2,6})\)\s*$/);
   if(match)out.add((match[1]||match[0]).toUpperCase());
 }
 return [...out].sort().slice(0,150);
}'''

NEXT_SELECTORS = [
  'button[aria-label="Next Page"]','button[aria-label="Next"]',
  'a[aria-label="Next Page"]','a[aria-label="Next"]',
  '[title="Next Page"]','[title="Next"]',
  '.pagination .next:not(.disabled)', 'a[rel="next"]',
  '[data-bind*="nextPage"]', '[data-bind*="nextCatalogPage"]',
  '[aria-label*="next" i]', '[title*="next" i]',
  '[data-action="next"]', 'button[ng-click*="next"]', '.paginator-next',
  '.pagination-next:not(.disabled)', 
]

def _pick_browser(p):
    from playwright.sync_api import Error
    choices=[]
    path=os.environ.get('SA_BROWSER_PATH','').strip()
    if path: choices.append({'executable_path':path})
    if os.name=='nt':choices.extend([{'channel':'msedge'},{'channel':'chrome'}])
    elif os.uname().sysname=='Darwin':choices.extend([{'channel':'chrome'},{'channel':'msedge'}])
    choices.append({})
    failures=[]
    for args in choices:
        try:return p.chromium.launch(headless=True,**args)
        except Error as exc:failures.append(str(exc).splitlines()[0][:100])
    raise RuntimeError('No supported Chromium/Edge browser is available for MyOCC bulk scans. '
         'Install Edge/Chrome locally, or run "python -m playwright install chromium". '
         + '; '.join(failures[-2:]))

def _subjects_for_scan(page,seed,configured):
    explicit=[x for x in configured if SUBJECT.fullmatch(x)]
    if explicit:return list(dict.fromkeys(explicit))
    from_url=parse_qs(urlsplit(seed).query).get('subjects',[])
    parsed=[v.upper().strip() for item in from_url for v in item.split(',')]
    parsed=[v for v in parsed if SUBJECT.fullmatch(v)]
    if parsed:return list(dict.fromkeys(parsed))
    # User requested all departments: attempt the public subject list, not a guessed list.
    page.goto(urlunsplit((*urlsplit(seed)[:3],'','')),wait_until='domcontentloaded',timeout=18000)
    page.wait_for_timeout(1600)
    found=page.evaluate(DISCOVER_SUBJECTS_JS)
    if not found:
        raise ValueError('MyOCC did not expose a readable subject list. Enter one or more subject codes '
                         '(for example CIS, CSC) in Bulk Import Catalog. Nothing has been imported.')
    return found

def _collect_subject(page, url, subject, budget, callback):
    page.goto(url,wait_until='domcontentloaded',timeout=20000)
    page.wait_for_timeout(1100)
    seen=set(); results={}; checked=0; errs=[]; more_possible=False
    for _ in range(budget):
        # Wait briefly for client-rendered search results to appear.
        try:page.wait_for_function("!!document.body && /[A-Z]{2,6}[- ]\\d{2,4}/.test(document.body.innerText)",timeout=4500)
        except Exception:pass
        # Expand descriptive cards; limit clicks to avoid spending minutes on a broken UI.
        for selector in ['a:has-text("more")','button:has-text("more")']:
            try:
                elems=page.locator(selector)
                for n in range(min(elems.count(),45)):
                    el=elems.nth(n)
                    if el.is_visible(timeout=400):el.click(timeout=650)
            except Exception:continue
        data=page.evaluate(EXTRACT_PAGE_JS,subject)
        checked+=1
        for item in data['courses']:
            old=results.get(item['code'])
            if not old or len(item['description'])>len(old['description']):results[item['code']]=item
        callback(checked,list(results.values()))
        fingerprint='|'.join(sorted(results.keys()))+'|'+str(data.get('headings',0))
        if fingerprint in seen:
            errs.append('Pagination did not change visible course results for '+subject)
            more_possible=True
            break
        seen.add(fingerprint)
        advanced=False
        for selector in NEXT_SELECTORS:
            try:
                el=page.locator(selector).first
                if el.count() and el.is_visible() and el.is_enabled():
                    el.click(timeout=1500)
                    page.wait_for_timeout(1100)
                    advanced=True;break
            except Exception:continue
        if not advanced:break
    else:more_possible=True
    if not results:
        errs.append('No '+subject+' course headings were rendered. Page sample: '+str(data.get('text_excerpt',''))[:220])
    elif not any(item['description'] for item in results.values()):
        errs.append('Course headings found for '+subject+', but no usable descriptions were visible')
    return list(results.values()),checked,more_possible,errs

def collect_myocc(seed, institution, subjects, max_pages, progress):
    """Return extracted records, visited result pages, partial flag and warnings.

    Each subject is opened as a public search URL. Browser session is isolated and
    never loads private user cookies, even when the operator is signed in elsewhere.
    """
    try:from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError('MyOCC bulk scanning needs the bundled Playwright browser driver. '
            'Install application requirements again; no AI service or API key is needed.') from exc
    from .catalog_bulk import _merge_course
    base=urlsplit(seed)
    if base.scheme!='https' or not base.hostname:raise ValueError('Invalid MyOCC source URL')
    root=urlunsplit((base.scheme,base.netloc,re.sub(r'/Search/?$', '', base.path, flags=re.I).rstrip('/'),'',''))
    validate_url(root,institution)
    found={};pages=0;warnings=[];partial=False
    with sync_playwright() as p:
        browser=_pick_browser(p)
        try:
            context=browser.new_context(accept_downloads=False,ignore_https_errors=False)
            page=context.new_page()
            # Never use a logged-in browser profile: public data only.
            codes=_subjects_for_scan(page,root if not parse_qs(base.query).get('subjects') else seed,subjects)
            if len(codes)>150:raise ValueError('Subject discovery exceeded the allowed limit')
            for code in codes:
                if pages>=max_pages:partial=True;break
                params=urlencode({'subjects':code})
                target=urlunsplit((base.scheme,base.netloc,urlsplit(root).path.rstrip('/')+'/Search',params,''))
                validate_url(target,institution)
                def track(local_pages,entries):
                    for entry in entries:_merge_course(found,entry)
                    progress(pages+local_pages,len(found))
                rows,visited,incomplete,problems=_collect_subject(page,target,code,max_pages-pages,track)
                pages+=visited
                for row in rows:_merge_course(found,row)
                warnings.extend(problems[:2]);partial |= (incomplete or not bool(rows))
        finally:browser.close()
    # A result set with no pagination metadata cannot certify completeness.
    warnings.append('MyOCC may hide additional results or omit historical catalog-year information; compare with the official academic catalog.')
    return list(found.values()),pages,partial,warnings[:25]
