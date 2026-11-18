"""Regression checks for missing python-docx XML data in frozen desktop builds."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from docx import Document
from app.documents import extract, template_sections

ROOT = Path(__file__).resolve().parents[1]


def test_blank_header_footer_are_not_created_while_extracting():
    with TemporaryDirectory() as folder:
        path = Path(folder) / 'plain.docx'
        d = Document()
        d.add_paragraph('STUDENT LEARNING OUTCOMES:')
        d.add_paragraph('Students can demonstrate comprehension.')
        d.save(path)
        # When undefined headers are mistakenly opened, python-docx will
        # call HeaderPart.new() / FooterPart.new() to create them.
        with patch('docx.parts.hdrftr.HeaderPart.new', side_effect=AssertionError('Created header during extraction')), \
             patch('docx.parts.hdrftr.FooterPart.new', side_effect=AssertionError('Created footer during extraction')):
            blocks = extract(path)['blocks']
            sections = template_sections(path)
        assert any('STUDENT LEARNING OUTCOMES:' in b['text'] for b in blocks)
        assert any(s['heading'] == 'STUDENT LEARNING OUTCOMES' for s in sections)


def test_existing_header_is_still_extracted():
    with TemporaryDirectory() as folder:
        path = Path(folder) / 'with-header.docx'
        d = Document()
        d.add_paragraph('Policy')
        d.sections[0].header.paragraphs[0].text = 'Real header text'
        d.save(path)
        with patch('docx.parts.hdrftr.HeaderPart.new', side_effect=AssertionError('Created header during extraction')):
            blocks=extract(path)['blocks']
        assert any('Real header text' in b['text'] for b in blocks)


def test_mac_build_gathers_docx_package_data_and_verifies_output():
    script=(ROOT/'packaging/macos/build-macos.sh').read_text()
    assert '--collect-data docx' in script
    assert 'Contents/Frameworks/docx/templates/$resource' in script
    assert 'default-header.xml' in script


def test_windows_build_gathers_docx_package_data_and_verifies_output():
    script=(ROOT/'packaging/windows/build-windows.ps1').read_text()
    assert "'--collect-data','docx'" in script
    assert r'dist\SyllabusAuditor\_internal\docx\templates' in script
    assert 'default-header.xml' in script
