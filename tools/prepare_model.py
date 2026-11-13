"""BUILD-TIME ONLY: downloads/verifies open-weight model for offline distribution.
No download is attempted by the running Syllabus Auditor web application.
"""
from pathlib import Path
from urllib.request import Request,urlopen
import hashlib,sys,os
ROOT=Path(__file__).resolve().parent.parent
DEST=ROOT/'models'/'Qwen3-1.7B-Q4_K_M.gguf'
# Antigma Qwen3-1.7B Q4_K_M, upstream Qwen Apache-2.0
URL='https://huggingface.co/Antigma/Qwen3-1.7B-GGUF/resolve/main/qwen3-1.7b-q4_k_m.gguf'
SHA256='a7f6720f68f4a4567ebf7e3257041dd0b72077b518efe56890aec3516b59b9de'

def verify(path):
    digest=hashlib.sha256()
    with path.open('rb') as file:
        for chunk in iter(lambda:file.read(8*1024*1024),b''): digest.update(chunk)
    return digest.hexdigest()==SHA256

def main():
    DEST.parent.mkdir(parents=True,exist_ok=True)
    if DEST.is_file():
        if verify(DEST):print('Model is present and SHA256 verified:',DEST);return
        raise SystemExit('Existing model hash mismatch; delete the corrupt file before rebuilding')
    tmp=DEST.with_suffix('.partial')
    print('Downloading model at build time (not from the running application):',URL,flush=True)
    req=Request(URL,headers={'User-Agent':'SyllabusAuditorOfflineBuilder/1.0'})
    try:
        with urlopen(req,timeout=60) as src,tmp.open('wb') as out:
            while block:=src.read(4*1024*1024):
                out.write(block)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    if not verify(tmp):
        tmp.unlink(missing_ok=True)
        raise SystemExit('Downloaded file has incorrect SHA256; refusing to include it')
    tmp.replace(DEST)
    print('Verified GGUF model:',DEST)
if __name__=='__main__':main()
