"""Regression tests for separated catalog identifiers, titles and desktop CSS build."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest



def audit(*lines, code='CSC-220', title='Foundations of Computer Science', verified=True):
    from app.validation import audit_document
    blocks=[{'text':line,'location':f'Paragraph {i}', 'kind':'heading' if i==1 else 'paragraph'}
            for i,line in enumerate(lines,1)]
    doc={'blocks':blocks,'text':'\n'.join(lines),'ocr_pages':[]}
    course={'code':code,'title':title,'last_verified_at':'2026-11-14' if verified else '', 'source_url':'https://catalog.example.edu/course'}
    _, findings=audit_document(doc, [],course=course,use_ai=False)
    return {f['code']:f for f in findings}


def test_exact_title_with_course_code_prefix_passes_all_three():
    f=audit('CSC-220 Foundations of Computer Science')
    assert f['catalog_course_prefix']['status']=='passed'
    assert f['catalog_course_number']['status']=='passed'
    assert f['catalog_title']['status']=='passed'
    assert f['catalog_title']['observed']=='Foundations of Computer Science'
    assert f['catalog_course_prefix']['observed']=='CSC'
    assert f['catalog_course_number']['observed']=='220'


def test_screenshot_similar_title_requires_review_but_code_passes():
    f=audit('CSC-220 Foundations of Comp Science')
    assert f['catalog_course_prefix']['status']=='passed'
    assert f['catalog_course_number']['status']=='passed'
    assert f['catalog_title']['status']=='review'
    assert f['catalog_title']['observed']=='Foundations of Comp Science'
    assert 'wording differs' in f['catalog_title']['explanation']


def test_wrong_prefix_is_failed_independently_from_correct_number_and_title():
    f=audit('CIS-220 Foundations of Computer Science')
    assert f['catalog_course_prefix']['status']=='failed'
    assert f['catalog_course_number']['status']=='passed'
    assert f['catalog_title']['status']=='passed'


def test_wrong_number_is_failed_independently_from_correct_prefix_and_title():
    f=audit('CSC-221 Foundations of Computer Science')
    assert f['catalog_course_prefix']['status']=='passed'
    assert f['catalog_course_number']['status']=='failed'
    assert f['catalog_title']['status']=='passed'


def test_course_identifier_not_found_is_reviewed_not_assumed_from_course_title():
    f=audit('Foundations of Computer Science')
    assert f['catalog_course_prefix']['status']=='review'
    assert f['catalog_course_number']['status']=='review'
    assert f['catalog_title']['status']=='passed'


def test_prerequisite_code_does_not_override_course_heading():
    f=audit('CSC-220 Foundations of Computer Science', 'Prerequisites: CSC-111')
    assert f['catalog_course_prefix']['status']=='passed'
    assert f['catalog_course_number']['status']=='passed'


def test_explicit_code_field_and_separate_title():
    f=audit('Course Code: CSC-220','Course Title: Foundations of Computer Science')
    assert f['catalog_course_prefix']['status']=='passed'
    assert f['catalog_course_number']['status']=='passed'
    assert f['catalog_title']['status']=='passed'


def test_unverified_title_remains_review_even_when_wording_exact():
    f=audit('CSC-220 Foundations of Computer Science',verified=False)
    assert f['catalog_title']['status']=='review'
    assert f['catalog_course_prefix']['status']=='passed'


def test_corrected_docx_title_replacement_preserves_code(tmp_path):
    from docx import Document
    from app.documents import correct_docx
    source=tmp_path/'syllabus.docx'
    doc=Document();doc.add_paragraph('CSC-220 Foundations of Comp Science');doc.save(source)
    b,applied,skipped=correct_docx(source,[(1,'Foundations of Comp Science','Foundations of Computer Science')])
    out=tmp_path/'approved.docx';out.write_bytes(b)
    assert 'CSC-220 Foundations of Computer Science' in '\n'.join(p.text for p in Document(out).paragraphs)
    assert applied==[1] and not skipped


def _desktop_module():
    root=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location('desktop_dev_test',root/'tools'/'desktop_dev.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_desktop_css_build_skips_when_tailwind_not_installed(tmp_path):
    module=_desktop_module()
    with patch.object(module,'ROOT',tmp_path),patch.object(module,'CSS_SOURCE',tmp_path/'styles'/'tailwind.css'),\
         patch.object(module,'MANIFEST',tmp_path/'package.json'),patch.object(module,'CSS_OUTPUT',tmp_path/'app/static/tailwind.generated.css'):
        assert module.build_css() is None


def test_desktop_css_build_invokes_npm_and_checks_output(tmp_path):
    module=_desktop_module()
    source=tmp_path/'styles/tailwind.css';source.parent.mkdir();source.write_text('@import "tailwindcss";')
    manifest=tmp_path/'package.json';manifest.write_text('{"scripts":{"build":"npm run build:css"}}')
    out=tmp_path/'app/static/tailwind.generated.css';out.parent.mkdir(parents=True)
    (tmp_path/'node_modules/.bin').mkdir(parents=True)
    def run(cmd,**kwargs):
        assert cmd==['npm','run','build']
        assert kwargs['cwd']==tmp_path
        out.write_text('/* compiled CSS */'+'a'*140)
    with patch.object(module,'ROOT',tmp_path),patch.object(module,'CSS_SOURCE',source),\
         patch.object(module,'MANIFEST',manifest),patch.object(module,'CSS_OUTPUT',out),\
         patch.object(module.subprocess,'run',side_effect=run) as invoked:
        assert module.build_css('npm')=='npm'
        invoked.assert_called_once()


def test_desktop_css_incomplete_installation_is_error(tmp_path):
    module=_desktop_module()
    manifest=tmp_path/'package.json';manifest.write_text('{}')
    with patch.object(module,'CSS_SOURCE',tmp_path/'styles/tailwind.css'), patch.object(module,'MANIFEST',manifest):
        with pytest.raises(RuntimeError,match='Incomplete Tailwind'):
            module.build_css('npm')
