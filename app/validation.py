"""Evidence-first syllabus validation: deterministic verdicts, AI-assisted navigation."""
import re, json
from rapidfuzz import fuzz
from .documents import infer_course_code
from .ai import ai

HEADINGS={
 'description':['course description','catalog description','description','course overview','about this course'],
 'title':['course title','course name','title'],
 'credits':['credits','credit hours','credit value'],
 'prerequisites':['prerequisites','pre requisites','prerequisite','required prior courses'],
}

def norm(value):
    value=str(value or '').lower().replace('–','-').replace('—','-')
    return re.sub(r'\s+',' ',value).strip()

def letters(value): return re.sub(r'[^a-z0-9]+',' ',norm(value)).strip()
def similarity(a,b): return fuzz.ratio(letters(a),letters(b))/100

def candidate_segments(blocks, target='', keys=''):
    terms=[x.strip() for x in (keys or '').replace(';',',').split(',') if x.strip()]
    terms += HEADINGS.get(target,[])
    if not terms: terms=[target]
    scored=[]
    for i,b in enumerate(blocks):
        txt=b['text']
        if not txt.strip(): continue
        head=' '.join(txt.split()[:12])[:110]
        score=max((max(fuzz.partial_ratio(letters(term),letters(head))/100,
                      fuzz.ratio(letters(term),letters(head))/100) if letters(term) else 0 for term in terms),default=0)
        if score>=.59:
            content=txt
            if len(txt)<125:
                content+='\n'+'\n'.join(x['text'] for x in blocks[i+1:i+5])
            scored.append({'text':content[:3500],'location':b['location'],'score':score,'index':i})
    scored.sort(key=lambda c:c['score'],reverse=True)
    return scored[:10]

def locate_content(blocks,name,expected='',keywords='',mode='exact',category='policy',use_ai=True):
    segments=candidate_segments(blocks,name if name in HEADINGS else '',keywords or name)
    if expected:
        ex=letters(expected)
        for i,b in enumerate(blocks):
            txt=b['text']
            # exact and fuzzy full blocks; never infer from isolated 2-word fragments
            score=max(similarity(txt,expected),fuzz.partial_ratio(ex,letters(txt))/100 if len(letters(txt))>=min(25,len(ex)) and len(ex)>=30 else 0)
            if score>.65:
                segments.append({'text':txt,'location':b['location'],'score':score,'index':i})
        # multi-block contiguous paragraphs for policy statements
        for i in range(len(blocks)):
            joined=' '.join(x['text'] for x in blocks[i:i+5])
            if len(joined)>70 and len(ex)>=30:
                score=fuzz.partial_ratio(ex,letters(joined))/100
                if score>.72:
                    segments.append({'text':joined[:3500],'location':blocks[i]['location'],'score':score,'index':i})
    # dedupe per location while retaining highest scores
    unique={}
    for s in segments:
        if s['location'] not in unique or s['score']>unique[s['location']]['score']: unique[s['location']]=s
    segments=sorted(unique.values(),key=lambda x:x['score'],reverse=True)[:10]
    choice=segments[0] if segments else None
    if use_ai and segments and (not choice or choice['score']<.87 or len(segments)>1 and choice['score']-segments[1]['score']<.07):
        answer=ai.classify({'name':name,'category':category,'keywords':keywords},segments)
        if answer: choice=answer['candidate'];choice['ai_confidence']=answer['confidence']
    return choice

def _finding(code,title,category,status,severity,expected='',observed='',location='',reason='',url='',confidence=0,evidence=None,requirement_id=None):
    return {'code':code,'title':title,'category':category,'status':status,'severity':severity,
        'expected':expected,'observed':observed,'location':location,'explanation':reason,'source_url':url,
        'confidence':round(confidence,2),'evidence_json':json.dumps(evidence or {}),'requirement_id':requirement_id}

def _check_text(name,expected,mode,blocks,severity,category,req_id=None,variants=None,keywords='',source_url='',use_ai=True):
    variants=variants or []
    found=locate_content(blocks,name,expected,keywords,mode,category,use_ai=use_ai)
    loc=found['location'] if found else ''
    observed=found['text'] if found else ''
    confidence=found.get('ai_confidence',found['score']) if found else 0
    if not expected and mode not in ('present','heading'):
        return _finding(name,name,category,'review',severity,expected,observed,loc,'The required reference text has not been configured.',source_url,confidence,requirement_id=req_id)
    if mode=='heading':
        head=found and max((similarity(line,name) for line in observed.split('\n')[:2]),default=0)
        passed=bool(found and (found['score']>=.82 or head>=.82))
        return _finding(name,name,category,'passed' if passed else 'failed',severity,expected,observed,loc,
            'Recognized section heading.' if passed else 'Required template heading not found.',source_url,confidence,requirement_id=req_id)
    if mode=='present':
        found_ok=bool(found and found['score']>=.8)
        return _finding(name,name,category,'passed' if found_ok else 'failed',severity,expected,observed,loc,
            'Required section located.' if found_ok else 'Required section not located.',source_url,confidence,requirement_id=req_id)
    if not found:
        return _finding(name,name,category,'failed',severity,expected,'','','No matching passage was found in the syllabus.',source_url,0,requirement_id=req_id)
    expected_options=[expected]+[v for v in variants if v]
    # Concatenated text may include a label or additional fields. Check normalized substring for exact text.
    if len(expected.strip())<=3 and expected.strip().isdigit():
        is_exact=any(bool(re.search(r'(?<!\d)'+re.escape(p.strip())+r'(?!\d)',observed)) for p in expected_options)
    else:
        is_exact=any(norm(p) and norm(p) in norm(observed) for p in expected_options)
    if is_exact:
        return _finding(name,name,category,'passed',severity,expected,observed,loc,'Approved text matched.',source_url,1,requirement_id=req_id)
    s=max((similarity(observed,e) for e in expected_options if e),default=0)
    partial=max((fuzz.partial_ratio(letters(e),letters(observed))/100 for e in expected_options if e and len(letters(e))>=20),default=0)
    if mode=='semantic':
        if max(s,partial)>=.90:
            status='passed'; reason='High-confidence equivalent wording found; verify if exact wording is required.'
        elif max(s,partial)>=.72:
            status='review';reason='Possible semantic equivalent; human verification required.'
        else: status='failed';reason='Matching section differs substantially from required meaning.'
    else:
        status='warning' if max(s,partial)>=.82 else 'failed'
        reason='Expected wording was not found verbatim. Similar passage detected.' if status=='warning' else 'Located section does not contain required approved wording.'
    return _finding(name,name,category,status,severity,expected,observed,loc,reason,source_url,confidence,requirement_id=req_id)

def audit_document(extracted,requirements,course=None,template=None,use_ai=True):
    blocks=extracted['blocks']; full=extracted['text']; findings=[]
    code=infer_course_code(full)
    if not full.strip():
        findings.append(_finding('extraction','Document text','document','review','critical',reason='No text could be extracted. OCR may be unavailable or scan unreadable.'))
        return code,findings
    if extracted.get('ocr_pages') and any(x<0 for x in extracted['ocr_pages']):
        findings.append(_finding('ocr','OCR coverage','document','review','warning',reason='OCR was not available for one or more image-based pages. Some text may be missing.'))
    if course:
        # Guard against checking a wrong course record
        if code and course['code'].upper()!=code.upper():
            findings.append(_finding('course_code','Course identifier','catalog','failed','critical',course['code'],code,'Beginning of document','Syllabus course code differs from selected catalog record.',course.get('source_url',''),1))
        for key,label in [('title','Course title'),('description','Course description'),('credits','Credit hours'),('prerequisites','Prerequisites')]:
            value=course.get(key,'')
            if not value: continue
            mode='exact' if key=='description' else 'semantic' if key in ('title','prerequisites') else 'exact'
            # Match the expected block, then compare. Description must stay verbatim.
            finding=_check_text(label,value,mode,blocks,'critical' if key=='description' else 'warning','catalog',keywords=','.join(HEADINGS.get(key,[])),source_url=course.get('source_url',''),use_ai=use_ai)
            finding['code']='catalog_'+key
            if key=='description' and not course.get('last_verified_at'):
                if finding['status']=='passed': finding['status']='review'
                finding['explanation']+=' The catalog reference has not been verified against its source.'
            findings.append(finding)
    elif code:
        findings.append(_finding('course_reference','Course catalog reference','catalog','review','warning',observed=code,reason='No matching institution/course/year reference is available. Official catalog validation could not be completed.'))
    for req in requirements:
        active_year=req.get('academic_year','')
        try: variants=json.loads(req.get('variants_json','[]'))
        except Exception: variants=[]
        finding=_check_text(req['name'],req.get('expected_text',''),req['mode'],blocks,req['severity'],req['category'],
            req['id'],variants,req.get('keywords',''),req.get('source_url',''),use_ai=use_ai)
        finding['code']='req_'+str(req['id'])
        findings.append(finding)
    if template:
        try: sections=json.loads(template.get('sections_json') or '[]')
        except Exception: sections=[]
        for section in sections:
            if not section.get('required'): continue
            mode=section.get('mode','heading')
            if mode not in ('exact','semantic','heading','present'):mode='heading'
            expected=section.get('expected_text','') if mode in ('exact','semantic') else ''
            match=_check_text(section['heading'],expected,mode,blocks,'warning','template',
                              keywords=section['heading'],use_ai=use_ai)
            match['code']='template_'+section['heading'].lower().replace(' ','_')[:70]
            findings.append(match)
    return code,findings
