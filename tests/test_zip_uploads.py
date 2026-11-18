"""Archive import safety and batch-limit regression tests (no external services)."""
import io
import stat
import zipfile

import pytest
from docx import Document

from app.documents import validate_upload
from app.zip_uploads import expand_syllabus_uploads


def archive(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for name, content in entries:
            z.writestr(name, content)
    return buf.getvalue()


def docx_bytes():
    doc = Document()
    doc.add_paragraph('CSC-220 Foundations of Computation')
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def expand(files):
    return expand_syllabus_uploads(files, validate_upload)


def test_zip_folder_with_pdf_docx_txt_and_metadata():
    z = archive([
        ('CS/CSC-220.docx', docx_bytes()),
        ('CS/subfolder/CSC-221.pdf', b'%PDF-1.4\nminimal'),
        ('ENG/ENG-101.txt', b'ENG-101 English Composition'),
        ('__MACOSX/._CSC-220.docx', b'garbage'),
        ('.DS_Store', b'garbage'),
        ('notes.csv', b'not a syllabus'),
        ('nested.zip', b'another archive'),
    ])
    staged, ignored, preview = expand([('class.zip', z)])
    assert [x[1] for x in staged] == ['.docx', '.pdf', '.txt']
    assert [x[0] for x in staged] == [
        'CS - CSC-220.docx', 'CS - subfolder - CSC-221.pdf', 'ENG - ENG-101.txt'
    ]
    assert ignored == 4
    assert len(preview) == 2


def test_direct_files_and_zip_in_single_batch():
    files = [('one.txt', b'CSC-220 course'), ('class.zip', archive([('two.txt', b'CSC-221 course')]))]
    staged, ignored, _ = expand(files)
    assert len(staged) == 2 and ignored == 0


def test_duplicate_names_are_not_lost():
    z = archive([('Student A/syllabus.txt', b'first'), ('Student B/syllabus.txt', b'second'),
                 ('Student A/syllabus.txt', b'third')])
    staged, _, _ = expand([('a.zip', z)])
    assert len(staged) == 3
    assert len({x[0].lower() for x in staged}) == 3


@pytest.mark.parametrize('name', [
    '../evil.txt', '/etc/evil.txt', 'X:/evil.txt', 'folder/../../evil.txt',
    r'folder\..\evil.txt', 'folder//evil.txt', 'folder/./evil.txt'
])
def test_unsafe_paths_rejected_atomically(name):
    z = archive([('good.txt', b'CSC-220'), (name, b'bad')])
    with pytest.raises(ValueError, match='Unsafe ZIP entry path'):
        expand([('attack.zip', z)])


def test_symlink_entry_rejected():
    info = zipfile.ZipInfo('link.txt')
    info.create_system = 3
    info.external_attr = ((stat.S_IFLNK | 0o777) << 16)
    z = archive([('ordinary.txt', b'CSC-220'), (info, b'target')])
    with pytest.raises(ValueError, match='symbolic link'):
        expand([('symlinks.zip', z)])


def test_invalid_zip_rejected():
    with pytest.raises(ValueError, match='invalid'):
        expand([('broken.zip', b'garbage')])


def test_empty_of_supported_files_rejected():
    with pytest.raises(ValueError, match='No supported syllabus documents'):
        expand([('other.zip', archive([('README.md', b'Not a syllabus')]))])


def test_too_many_docs_rejected():
    z = archive([(f'file{i}.txt', b'document') for i in range(101)])
    with pytest.raises(ValueError, match='100 syllabi'):
        expand([('many.zip', z)])


def test_large_document_rejected():
    z = archive([('huge.txt', b'A' * (26 * 1024 * 1024))])
    with pytest.raises(ValueError, match='per-document size limit'):
        expand([('large.zip', z)])


def test_corrupt_docx_rejected_without_partial_import():
    z = archive([('good.txt', b'CSC-220'), ('fake.docx', b'not a Word document')])
    with pytest.raises(ValueError, match='fake.docx'):
        expand([('corrupt.zip', z)])


def test_duplicate_direct_and_archive_names_suffixed():
    staged, _, _ = expand([('same.txt', b'one'), ('example.zip', archive([('same.txt', b'two')]))])
    assert [f[0] for f in staged] == ['same.txt', 'same (2).txt']


def test_allows_unsupported_large_entry_without_extracting_it():
    z = archive([('huge.jpg', b'A' * (27 * 1024 * 1024)), ('valid.txt', b'CSC-220')])
    staged, ignored, _ = expand([('mixed.zip', z)])
    assert len(staged) == 1 and ignored == 1


def test_invalid_direct_file_rejected():
    with pytest.raises(ValueError, match='Accepted file types'):
        expand([('invalid.exe', b'not a syllabus')])
