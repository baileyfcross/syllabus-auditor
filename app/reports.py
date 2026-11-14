"""PDF/DOCX/CSV reports from persisted audit evidence."""
import io, csv, zipfile
from pathlib import Path
from xml.sax.saxutils import escape
from docx import Document
from docx.shared import Inches,Pt
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from .database import one, all_rows
from .approval import review_summary

def load(audit_id):
    audit=one('SELECT a.*,i.name AS institution_name,t.name AS template_name FROM audits a JOIN institutions i ON i.id=a.institution_id LEFT JOIN templates t ON t.id=a.template_id WHERE a.id=?',(audit_id,))
    if not audit:return None,None
    findings=all_rows('SELECT * FROM findings WHERE audit_id=? ORDER BY CASE status WHEN "failed" THEN 0 WHEN "review" THEN 1 WHEN "warning" THEN 2 ELSE 3 END,id',(audit_id,))
    return audit,findings

def pdf_report(audit,findings):
    buffer=io.BytesIO(); doc=SimpleDocTemplate(buffer,pagesize=letter,rightMargin=46,leftMargin=46,topMargin=52,bottomMargin=50)
    styles=getSampleStyleSheet();styles.add(ParagraphStyle(name='Subtle',parent=styles['Normal'],fontSize=9,textColor=colors.HexColor('#657084'),spaceAfter=8))
    body=[Paragraph('SYLLABUS AUDITOR',styles['Title']),Paragraph('Audit report | '+escape(str(audit['institution_name'])),styles['Subtle']),
          Paragraph('<b>File:</b> '+escape(audit['filename']),styles['Normal']),
          Paragraph('<b>Course:</b> '+escape(audit['course_code'] or 'Unidentified')+' &nbsp; <b>Year:</b> '+escape(audit['academic_year'] or '-'),styles['Normal']),
          Paragraph('<b>Template:</b> '+escape(audit['template_name'] or 'Institution rules only'),styles['Normal']),
          Paragraph('<b>Status:</b> '+escape('Approved' if audit.get('approved_at') else audit['status'])+' &nbsp; <b>Date:</b> '+escape(audit['completed_at'] or audit['created_at']),styles['Normal']),Spacer(1,14)]
    if audit.get('approved_at'):
        body.append(Paragraph('<b>Approved on:</b> '+escape(audit['approved_at'])+' (review decisions locked)',styles['Normal']))
    review=review_summary(findings)
    body.append(Paragraph(f"Review decisions: {review['accepted']} correction(s) accepted, {review['dismissed']} waived, {review['remaining']} pending. Original issue classifications remain visible.",styles['Subtle']))
    data=[['Passed','Warnings','Failed','Needs Review'],[str(audit[k]) for k in ['passed','warnings','failed','review']]]
    table=Table(data,colWidths=[120]*4);table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#edf2f9')),('GRID',(0,0),(-1,-1),.4,colors.HexColor('#d4dbe5')),('PADDING',(0,0),(-1,-1),8)]));body+=[table,Spacer(1,18)]
    for f in findings:
        decision=' / CORRECTION ACCEPTED' if f['accepted'] else ' / DISMISSED / WAIVED' if f['dismissed'] else ''
        parts=[Paragraph(escape(f['title'])+' - '+escape(f['status'].upper()+decision),styles['Heading3']),
               Paragraph('<b>Location:</b> '+escape(f['location'] or 'Not located')+' &nbsp; <b>Severity:</b> '+escape(f['severity']),styles['Subtle']),
               Paragraph(escape(f['explanation'] or ''),styles['Normal'])]
        for label,k in [('Expected','expected'),('Observed','observed')]:
            if f.get(k): parts.append(Paragraph('<b>'+label+':</b> '+escape(f[k][:1800]).replace('\n','<br/>'),styles['Normal']))
        if f.get('source_url'): parts.append(Paragraph('<b>Source:</b> '+escape(f['source_url']),styles['Subtle']))
        parts.append(Spacer(1,10));body.append(KeepTogether(parts))
    doc.build(body);return buffer.getvalue()

def docx_report(audit,findings):
    d=Document();d.add_heading('Syllabus Auditor | Audit Report',0)
    for label,value in [('Institution',audit['institution_name']),('Document',audit['filename']),('Course',audit['course_code']),
                        ('Academic Year',audit['academic_year']),('Template',audit['template_name'] or 'Institution rules only'),
                        ('Completed',audit['completed_at'] or audit['created_at']),
                        ('Approval status','Approved '+audit['approved_at'] if audit.get('approved_at') else 'Not approved')]:d.add_paragraph(f'{label}: {value}')
    d.add_heading('Summary',level=1);d.add_paragraph(f"Passed: {audit['passed']}   Warnings: {audit['warnings']}   Failed: {audit['failed']}   Review: {audit['review']}")
    review=review_summary(findings)
    d.add_paragraph(f"Decisions: {review['accepted']} accepted corrections, {review['dismissed']} dismissed/waived, {review['remaining']} pending. Original classifications remain unchanged.")
    for f in findings:
        d.add_heading(f"{f['title']} [{f['status'].upper()}] - {'Accepted correction' if f['accepted'] else 'Dismissed/waived' if f['dismissed'] else 'Pending' if f['status']!='passed' else 'Passed'}",level=2)
        for label,k in [('Severity','severity'),('Location','location'),('Explanation','explanation'),('Expected','expected'),('Observed','observed'),('Official source','source_url')]:
            if f.get(k): d.add_paragraph(f'{label}: {f[k]}')
    out=io.BytesIO();d.save(out);return out.getvalue()

def csv_report(audits):
    out=io.StringIO();w=csv.writer(out);w.writerow(['Audit ID','Document','Course','Status','Passed','Warnings','Failed','Needs Review','Date','Approved At'])
    for a in audits:w.writerow([a.get(k,'') for k in ['id','filename','course_code','status','passed','warnings','failed','review','completed_at','approved_at']])
    return out.getvalue().encode('utf-8-sig')

def batch_zip(job_id):
    audits=all_rows('SELECT * FROM audits WHERE job_id=? ORDER BY id',(job_id,))
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('batch-summary.csv',csv_report(audits))
        for a in audits:
            audit,findings=load(a['id'])
            if audit and audit['status']=='complete':
                z.writestr(f'audit-{a["id"]}.pdf',pdf_report(audit,findings))
    return stream.getvalue()
