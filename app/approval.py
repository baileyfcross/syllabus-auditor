"""Immutable, review-backed approved syllabus downloads.

A reviewer decision never silently reclassifies an unverified finding as a pass.
Accepted edits are applied only where deterministic replacement is unambiguous.
The approval appendix records any amendments that could not be placed in the body.
"""
import io
from pathlib import Path
from xml.sax.saxutils import escape
from docx import Document
import fitz
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from .documents import correct_docx


def review_summary(findings):
    relevant=[f for f in findings if f['status']!='passed']
    accepted=sum(bool(f['accepted']) for f in relevant)
    dismissed=sum(bool(f['dismissed']) for f in relevant)
    return {
        'total':len(findings), 'passed':len(findings)-len(relevant),
        'actionable':len(relevant), 'accepted':accepted, 'dismissed':dismissed,
        'reviewed':accepted+dismissed,'remaining':len(relevant)-accepted-dismissed,
        'pending_warnings':sum(f['status']=='warning' and not (f['accepted'] or f['dismissed']) for f in relevant),
        'pending_failed':sum(f['status']=='failed' and not (f['accepted'] or f['dismissed']) for f in relevant),
        'pending_review':sum(f['status']=='review' and not (f['accepted'] or f['dismissed']) for f in relevant)
    }


def approval_lines(findings,applied):
    result=[]
    for f in findings:
        if f['status']=='passed':continue
        label='ACCEPTED CORRECTION' if f['accepted'] else 'DISMISSED / WAIVED'
        mode=('automatically applied to DOCX text' if f['id'] in applied else
              'documented amendment (original passage remains)' if f['accepted'] else
              'waiver recorded; original wording remains')
        result.append({'title':f['title'], 'code':f['code'],'status':f['status'],
                       'decision':label, 'handling':mode,'expected':f['expected'],
                       'observed':f['observed']})
    return result


def _append_docx(doc, snapshot, lines):
    doc.add_page_break()
    doc.add_heading('Syllabus Auditor | Approval Record',level=1)
    doc.add_paragraph(f"Audit #{snapshot['audit_id']}  |  Approved {snapshot['approved_at']}")
    doc.add_paragraph(f"Reviewer: {snapshot['approved_by']}")
    s=snapshot['summary']
    doc.add_paragraph(f"Passed: {s['passed']}  |  Corrections accepted: {s['accepted']}  |  Findings dismissed: {s['dismissed']}")
    doc.add_paragraph('This approval confirms completion of the review workflow, not independent verification of waived findings. '
                      'Accepted corrections are incorporated into the document only where safely possible. '
                      'Any unplaced corrections are authoritative amendments documented below; '
                      'read this record together with the syllabus.')
    for item in lines:
        doc.add_heading(f"{item['title']} - {item['decision']}",level=2)
        doc.add_paragraph(item['handling'])
        if item['expected']:
            doc.add_paragraph('Approved wording / proposed amendment: '+item['expected'][:7000])
        if item['observed']:
            doc.add_paragraph('Original wording: '+item['observed'][:5000])
    return doc


def _pdf_record(snapshot,lines):
    output=io.BytesIO()
    document=SimpleDocTemplate(output,pagesize=letter,rightMargin=47,leftMargin=47)
    ss=getSampleStyleSheet()
    ss.add(ParagraphStyle(name='ApprovalSmall',parent=ss['Normal'],fontSize=9,leading=13,spaceAfter=8))
    story=[Paragraph('SYLLABUS AUDITOR | APPROVAL RECORD',ss['Heading1']),
           Paragraph(f"Audit #{snapshot['audit_id']} | Approved {escape(snapshot['approved_at'])} | Reviewer: {escape(snapshot['approved_by'])}",ss['ApprovalSmall']),
           Paragraph('Review decisions are not evidence that waived discrepancies passed. The original PDF pages are unchanged; accepted amendments and waivers are documented in this appendix.',ss['ApprovalSmall']),Spacer(1,12)]
    s=snapshot['summary']
    story.append(Paragraph(f"Passed: {s['passed']} | Accepted amendments: {s['accepted']} | Waived: {s['dismissed']}",ss['ApprovalSmall']))
    for item in lines:
        story.append(Paragraph(escape(item['title'][:180]+' - '+item['decision']),ss['Heading3']))
        story.append(Paragraph(escape(item['handling']),ss['ApprovalSmall']))
        if item['expected']:
            story.append(Paragraph('<b>Approved wording / amendment:</b> '+escape(item['expected'][:6000]).replace('\n','<br/>'),ss['ApprovalSmall']))
        if item['observed']:
            story.append(Paragraph('<b>Original wording:</b> '+escape(item['observed'][:3500]).replace('\n','<br/>'),ss['ApprovalSmall']))
    document.build(story)
    return output.getvalue()


def build_approved_syllabus(source, filetype, findings, snapshot):
    """Produce an immutable copy with an explicit approval and amendment record."""
    source=Path(source)
    applied=[]
    if filetype=='.docx':
        replacements=[(f['id'],f['observed'],f['expected']) for f in findings
                      if f['status']!='passed' and f['accepted'] and f['observed'] and f['expected']]
        data,applied,skipped=correct_docx(source,replacements) if replacements else (source.read_bytes(),[],[])
        doc=Document(io.BytesIO(data))
        _append_docx(doc,snapshot,approval_lines(findings,set(applied)))
        output=io.BytesIO();doc.save(output);return output.getvalue()
    if filetype=='.pdf':
        with fitz.open(source) as original:
            with fitz.open(stream=_pdf_record(snapshot,approval_lines(findings,set())),filetype='pdf') as record:
                original.insert_pdf(record)
                return original.tobytes(garbage=3,deflate=True)
    if filetype=='.txt':
        original=source.read_text(encoding='utf-8-sig')
        lines=approval_lines(findings,set())
        summary=snapshot['summary']
        footer=[f"Syllabus Auditor - Approval Record | Audit #{snapshot['audit_id']}",
                f"Approved: {snapshot['approved_at']} | Reviewer: {snapshot['approved_by']}",
                f"Passed: {summary['passed']} | Accepted: {summary['accepted']} | Waived: {summary['dismissed']}",
                'The original syllabus text above is unchanged. Accepted wording is documented as amendments below.']
        for item in lines:
            footer.extend([f"{item['title']}: {item['decision']}",
                           'Approved wording / amendment: '+(item['expected'] or '(Not specified)'),
                           'Original wording: '+(item['observed'] or '(Not found)')])
        return (original+'\n\n'+'='*70+'\n'+'\n'.join(footer)+'\n').encode('utf-8')
    raise ValueError('Approved files must be DOCX, PDF or TXT')
