"""Offline document parsing with location-preserving text blocks."""
import io, re, zipfile
from pathlib import Path
from docx import Document
from docx.oxml.ns import qn
import fitz
from .config import MAX_UPLOAD

ACCEPTED={'.docx','.pdf','.txt'}

def validate_upload(filename,content):
    suffix=Path(filename).suffix.lower()
    if suffix not in ACCEPTED: raise ValueError('Accepted file types: DOCX, PDF, TXT')
    if not content or len(content)>MAX_UPLOAD: raise ValueError('File is empty or exceeds upload size limit')
    if suffix=='.pdf' and not content.startswith(b'%PDF'): raise ValueError('Invalid PDF file')
    if suffix=='.docx':
        if not zipfile.is_zipfile(io.BytesIO(content)) or len(content)<50: raise ValueError('Invalid DOCX file')
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            entries=z.infolist()
            if len(entries)>3000 or sum(item.file_size for item in entries)>75*1024*1024:
                raise ValueError('DOCX archive contains too much expanded data')
    if suffix=='.txt':
        try: content.decode('utf-8-sig')
        except UnicodeDecodeError: raise ValueError('TXT must be UTF-8 encoded')
    return suffix

def extract(path):
    path=Path(path)
    suffix=path.suffix.lower()
    blocks=[]; ocr_pages=[]
    if suffix=='.txt':
        for i,line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(),1):
            if line.strip(): blocks.append({'text':line.strip(),'location':f'Line {i}','page':1,'kind':'paragraph'})
    elif suffix=='.docx':
        doc=Document(path)
        number=0
        for content in doc.iter_inner_content():
            if hasattr(content,'rows'):
                for row in content.rows:
                    cells=[c.text.strip().replace('\n',' | ') for c in row.cells]
                    text=' | '.join(c for c in cells if c)
                    if text:
                        number+=1
                        blocks.append({'text':text,'location':f'Table row {number}','page':None,'kind':'table'})
            else:
                text=content.text.strip()
                if text:
                    number+=1
                    style=(content.style.name if content.style else '')
                    blocks.append({'text':text,'location':f'Paragraph {number}','page':None,'kind':'heading' if style.lower().startswith(('heading','title')) else 'paragraph'})
        for section in doc.sections:
            for area in [section.header,section.footer]:
                for p in area.paragraphs:
                    if p.text.strip(): blocks.append({'text':p.text.strip(),'location':'Header/Footer','page':None,'kind':'paragraph'})
    elif suffix=='.pdf':
        with fitz.open(path) as pdf:
            if len(pdf)>250: raise ValueError('PDF exceeds 250-page safety limit')
            for pno,page in enumerate(pdf,1):
                text=page.get_text('text').strip()
                if len(text)<35:
                    try:
                        import pytesseract
                        from PIL import Image
                        pix=page.get_pixmap(matrix=fitz.Matrix(1.8,1.8),alpha=False)
                        image=Image.open(io.BytesIO(pix.tobytes('png')))
                        ocr=pytesseract.image_to_string(image,config='--psm 3').strip()
                        if len(ocr)>len(text):
                            text=ocr; ocr_pages.append(pno)
                    except Exception:
                        ocr_pages.append(-pno)
                for i,line in enumerate(text.splitlines(),1):
                    line=line.strip()
                    if line: blocks.append({'text':line,'location':f'Page {pno}, line {i}','page':pno,'kind':'paragraph'})
    else: raise ValueError('Unsupported file')
    full='\n'.join(x['text'] for x in blocks)
    return {'blocks':blocks,'text':full,'ocr_pages':ocr_pages,'characters':len(full)}

def infer_course_code(text):
    candidates=re.findall(r'\b([A-Za-z]{2,5})\s*[-– ]\s*(\d{3,4}[A-Za-z]?)\b',text[:15000])
    ignore={'ISO','USA','HTTP','WWW'}
    for a,b in candidates:
        if a.upper() not in ignore: return f'{a.upper()}-{b.upper()}'
    return ''

def template_sections(path):
    data=extract(path)
    headings=[]
    for i,b in enumerate(data['blocks']):
        text=b['text'].strip()
        if len(text)>90 or len(text)<3: continue
        head=b['kind']=='heading' or (text.isupper() and 4<len(text)<65) or (text.endswith(':') and len(text)<65)
        if not head: continue
        if text.lower().startswith(('page ', 'table ', 'name:')): continue
        headings.append((i,text.rstrip(':'),b['location']))
    sections=[]
    for j,(i,heading,location) in enumerate(headings[:100]):
        next_idx=headings[j+1][0] if j+1<len(headings) else len(data['blocks'])
        # Preserve reference section text for optionally requiring exact/semantic matches.
        reference='\n'.join(x['text'] for x in data['blocks'][i+1:next_idx])[:4000]
        sections.append({'heading':heading,'location':location,'sample':reference[:500],
                         'expected_text':reference,'mode':'heading'})
    return sections

def correct_docx(original_path, replacements):
    """Make a separate edited copy; returns (bytes, applied, skipped).
    Uses conservative full-paragraph/cell substring replacement, preserving first run styling.
    """
    doc=Document(original_path)
    applied=[]; skipped=[]
    for finding_id,old,new in replacements:
        if not old or not new or len(old)<8 or old==new:
            skipped.append(finding_id); continue
        matches=[]
        for para in doc.paragraphs:
            if old in para.text: matches.append(para)
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        if old in para.text: matches.append(para)
        # Only replace unambiguous, fully matched paragraphs to avoid editing unrelated content.
        if len(matches)!=1:
            skipped.append(finding_id); continue
        p=matches[0]
        whole=p.text
        result=whole.replace(old,new,1)
        if p.runs:
            p.runs[0].text=result
            for r in p.runs[1:]: r.text=''
        else: p.add_run(result)
        applied.append(finding_id)
    buffer=io.BytesIO(); doc.save(buffer)
    return buffer.getvalue(),applied,skipped
